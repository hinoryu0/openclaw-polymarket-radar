#!/usr/bin/env python3
"""Kyiv Strike Edge Scanner (local-only)

Fetches Kyiv strike-related events/markets from Polymarket's public Gamma API and
computes simple "edge/signal" metrics:
  - p_yes (implied probability)
  - spread (bestAsk - bestBid) when available
  - volume24hr
  - price change: 1h / 24h (Gamma fields)
  - rewards (best-effort extraction when available)

Then compares *adjacent days* (based on market endDate) for similar markets to
highlight anomalies (e.g., tomorrow priced materially different than the next day).

Outputs:
  - Markdown report
  - JSON data (raw markets + derived fields + anomalies)

No deploy; runs as a standalone script.

Examples:
  python3 scripts/kyiv_strike_edge_scanner.py --out-dir memory/reports/kyiv-strike
  python3 scripts/kyiv_strike_edge_scanner.py --max-events 80 --max-markets 400

Notes:
  - Gamma API is unofficial/stability not guaranteed.
  - Event discovery uses a mix of Ukraine page scraping (best-effort) + API search.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

UKRAINE_PAGE = "https://polymarket.com/geopolitics/ukraine"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (OpenClaw kyiv-edge-scanner)"})


def _get(url: str, *, timeout: int = 30) -> requests.Response:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def _as_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _parse_json_maybe(x: Any) -> Any:
    if isinstance(x, str):
        s = x.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return json.loads(s)
            except Exception:
                return x
    return x


def prob_yes(m: Dict[str, Any]) -> Optional[float]:
    op = _parse_json_maybe(m.get("outcomePrices"))
    if isinstance(op, list) and op:
        return _as_float(op[0])
    return None


def spread(m: Dict[str, Any]) -> Optional[float]:
    bid = _as_float(m.get("bestBid"))
    ask = _as_float(m.get("bestAsk"))
    if bid is None or ask is None:
        return None
    return ask - bid


def fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "?%"
    return f"{x * 100:.1f}%"


def fmt_money(x: Any) -> str:
    v = _as_float(x)
    if v is None:
        return "$?"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}m"
    if v >= 1_000:
        return f"${v/1_000:.1f}k"
    return f"${v:.0f}"


def _date_from_end_date(m: Dict[str, Any]) -> Optional[str]:
    # Gamma typically returns ISO timestamps in endDate.
    s = m.get("endDate") or m.get("closeTime")
    if not isinstance(s, str) or not s:
        return None
    try:
        # allow both ...Z and offset
        if s.endswith("Z"):
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            t = dt.datetime.fromisoformat(s)
        return t.date().isoformat()
    except Exception:
        return None


def normalize_question_key(question: str) -> str:
    """Create a comparison key by stripping obvious date/time tokens.

    This allows comparing "Kyiv strike on Feb 6" vs "Kyiv strike on Feb 7".
    It's heuristic, but good enough to spot anomalies.
    """

    q = (question or "").lower().strip()
    q = re.sub(r"\s+", " ", q)

    # remove weekday names
    q = re.sub(r"\b(mon|tue|wed|thu|fri|sat|sun)(day)?\b", " ", q)

    # remove month names and common date formats
    months = "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december"
    q = re.sub(rf"\b({months})\b", " ", q)
    q = re.sub(r"\b\d{1,2}(st|nd|rd|th)\b", " ", q)
    q = re.sub(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", " ", q)
    q = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", q)

    # remove times like 9am, 21:00
    q = re.sub(r"\b\d{1,2}:\d{2}\b", " ", q)
    q = re.sub(r"\b\d{1,2}\s?(am|pm)\b", " ", q)

    q = re.sub(r"\s+", " ", q).strip()
    return q


def discover_kyiv_event_slugs_from_ukraine_page() -> List[str]:
    """Best-effort discovery of Kyiv strike event slugs from the Ukraine category page."""
    try:
        html = _get(UKRAINE_PAGE, timeout=40).text
    except Exception:
        return []

    ev_slugs = set()
    for m in re.finditer(r'href="/event/([^"/?#]+)', html):
        ev = m.group(1)
        if not ev:
            continue
        ev_l = ev.lower()
        if "kyiv" in ev_l and "strike" in ev_l:
            ev_slugs.add(ev)
    return sorted(ev_slugs)


def gamma_events_search(query: str, *, limit: int = 50, timeout: int = 35) -> List[Dict[str, Any]]:
    """Query Gamma events endpoint.

    Gamma supports several query params depending on backend version. We try a
    small set of common patterns and accept whichever returns JSON.
    """

    query = (query or "").strip()
    if not query:
        return []

    # Known-ish patterns: ?search=, ?q=, ?query=.
    params_variants = [
        {"search": query, "limit": str(limit)},
        {"q": query, "limit": str(limit)},
        {"query": query, "limit": str(limit)},
    ]

    for params in params_variants:
        try:
            r = SESSION.get(GAMMA_EVENTS, params=params, timeout=timeout)
            r.raise_for_status()
            js = r.json()
            if isinstance(js, list):
                return [x for x in js if isinstance(x, dict)]
        except Exception:
            continue

    return []


def fetch_event_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    try:
        r = _get(f"{GAMMA_EVENTS}?slug={requests.utils.quote(slug)}", timeout=25)
        js = r.json()
        if isinstance(js, list) and js and isinstance(js[0], dict):
            return js[0]
    except Exception:
        return None
    return None


def filter_kyiv_strike_markets(markets: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        q = (m.get("question") or "").lower()
        slug = (m.get("slug") or "").lower()
        if "kyiv" in q or "kyiv" in slug:
            # include strike, missile, drone, attack variants
            if any(w in q or w in slug for w in ("strike", "attack", "missile", "drone", "bomb")):
                out.append(m)
    # de-dup by id
    seen = set()
    uniq = []
    for m in out:
        mid = str(m.get("id"))
        if not mid or mid in seen:
            continue
        seen.add(mid)
        uniq.append(m)
    return uniq


def extract_rewards(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Best-effort: Gamma fields vary. Return a small dict or None."""
    candidates = {}
    for k in (
        "rewards",
        "reward",
        "liquidityRewards",
        "liquidityReward",
        "lpRewards",
        "incentives",
        "incentive",
    ):
        if k in m and m.get(k) is not None:
            candidates[k] = _parse_json_maybe(m.get(k))
    if candidates:
        return candidates
    return None


@dataclass
class DerivedMarket:
    id: str
    slug: str
    question: str
    url: str
    end_date: Optional[str]
    p_yes: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    volume24hr: Optional[float]
    ch_1h: Optional[float]
    ch_24h: Optional[float]
    rewards: Optional[Dict[str, Any]]
    key: str


def derive(m: Dict[str, Any]) -> DerivedMarket:
    slug = str(m.get("slug") or "")
    q = str(m.get("question") or "")
    return DerivedMarket(
        id=str(m.get("id") or ""),
        slug=slug,
        question=q,
        url=f"https://polymarket.com/event/{slug}" if slug else "",
        end_date=_date_from_end_date(m),
        p_yes=prob_yes(m),
        best_bid=_as_float(m.get("bestBid")),
        best_ask=_as_float(m.get("bestAsk")),
        spread=spread(m),
        volume24hr=_as_float(m.get("volume24hr")),
        ch_1h=_as_float(m.get("oneHourPriceChange")),
        ch_24h=_as_float(m.get("oneDayPriceChange")),
        rewards=extract_rewards(m),
        key=normalize_question_key(q),
    )


def adjacent_day_anomalies(items: List[DerivedMarket], *, threshold_pp: float = 15.0) -> List[Dict[str, Any]]:
    """Compare implied probabilities for adjacent days for similar markets.

    For each "key", we sort by end_date and compare consecutive entries.
    If p_yes differs by >= threshold_pp percentage points, flag.
    """

    by_key: Dict[str, List[DerivedMarket]] = {}
    for it in items:
        if not it.key or not it.end_date:
            continue
        by_key.setdefault(it.key, []).append(it)

    anomalies: List[Dict[str, Any]] = []

    for key, arr in by_key.items():
        arr_sorted = sorted(arr, key=lambda x: x.end_date)
        for a, b in zip(arr_sorted, arr_sorted[1:]):
            if a.p_yes is None or b.p_yes is None:
                continue
            # Only consider truly adjacent calendar days
            try:
                da = dt.date.fromisoformat(a.end_date)
                db = dt.date.fromisoformat(b.end_date)
            except Exception:
                continue
            if (db - da).days != 1:
                continue
            diff_pp = (b.p_yes - a.p_yes) * 100.0
            if abs(diff_pp) >= threshold_pp:
                anomalies.append(
                    {
                        "key": key,
                        "date_a": a.end_date,
                        "date_b": b.end_date,
                        "p_yes_a": a.p_yes,
                        "p_yes_b": b.p_yes,
                        "diff_pp": diff_pp,
                        "market_a": {"slug": a.slug, "question": a.question, "url": a.url},
                        "market_b": {"slug": b.slug, "question": b.question, "url": b.url},
                    }
                )

    # Sort by absolute difference
    anomalies.sort(key=lambda x: abs(float(x.get("diff_pp") or 0)), reverse=True)
    return anomalies


def render_markdown(items: List[DerivedMarket], anomalies: List[Dict[str, Any]]) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = []
    lines.append(f"# Kyiv Strike Edge Scanner")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append("")

    if anomalies:
        lines.append("## Adjacent-day anomalies (heuristic)")
        lines.append("")
        lines.append("Flagged when adjacent-day p(YES) differs by >= 15pp for similar questions.")
        lines.append("")
        for a in anomalies[:20]:
            diff_pp = float(a["diff_pp"])
            lines.append(
                f"- **{diff_pp:+.1f}pp** {a['date_a']} → {a['date_b']} | {a['market_a']['slug']} vs {a['market_b']['slug']}\n"
                f"  - A: {fmt_pct(a['p_yes_a'])} — {a['market_a']['question']}\n"
                f"  - B: {fmt_pct(a['p_yes_b'])} — {a['market_b']['question']}"
            )
        lines.append("")

    lines.append("## Markets (sorted by volume24hr)")
    lines.append("")
    lines.append("Columns: p(YES), spread (ask-bid), vol24h, Δ1h, Δ24h, endDate")
    lines.append("")

    items_sorted = sorted(items, key=lambda x: (x.volume24hr or 0.0), reverse=True)
    for it in items_sorted:
        sp = "?" if it.spread is None else f"{it.spread:.3f}"
        ch1 = "?" if it.ch_1h is None else f"{it.ch_1h:+.3f}"
        chd = "?" if it.ch_24h is None else f"{it.ch_24h:+.3f}"
        ed = it.end_date or "?"
        lines.append(
            f"- {fmt_pct(it.p_yes):>6} | spread {sp:>6} | vol {fmt_money(it.volume24hr)} | Δ1h {ch1:>7} | Δ24h {chd:>7} | {ed} | [{it.slug}]({it.url})"
        )
        # include rewards signal if present
        if it.rewards:
            reward_keys = ", ".join(sorted(it.rewards.keys()))
            lines.append(f"  - rewards: {reward_keys}")

    lines.append("")
    return "\n".join(lines).strip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="memory/reports/kyiv-strike-edge", help="Output directory")
    ap.add_argument("--max-events", type=int, default=50, help="Max events to pull via search")
    ap.add_argument("--max-markets", type=int, default=500, help="Cap markets processed")
    ap.add_argument("--threshold-pp", type=float, default=15.0, help="Anomaly threshold (percentage points)")
    ap.add_argument("--no-search", action="store_true", help="Skip Gamma search; use Ukraine page discovery only")
    args = ap.parse_args(argv)

    out_dir = os.path.join(os.path.dirname(__file__), "..", args.out_dir)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # 1) Discover event slugs from page
    slugs = set(discover_kyiv_event_slugs_from_ukraine_page())

    # 2) Optional search to catch new/hidden slugs
    if not args.no_search:
        for q in ("kyiv strike", "kyiv attack", "kyiv missile", "kyiv drone"):
            for ev in gamma_events_search(q, limit=max(10, args.max_events // 4))[: args.max_events]:
                s = ev.get("slug")
                title = (ev.get("title") or ev.get("name") or "")
                if isinstance(s, str) and s:
                    st = s.lower()
                    tt = str(title).lower()
                    if "kyiv" in st or "kyiv" in tt:
                        if any(w in st or w in tt for w in ("strike", "attack", "missile", "drone")):
                            slugs.add(s)

    slugs_list = sorted(slugs)

    # Fetch events and markets
    markets: List[Dict[str, Any]] = []
    events_ok = 0
    for slug in slugs_list:
        ev = fetch_event_by_slug(slug)
        if not ev:
            continue
        events_ok += 1
        ms = ev.get("markets")
        if isinstance(ms, list):
            markets.extend([m for m in ms if isinstance(m, dict)])

    filtered = filter_kyiv_strike_markets(markets)
    if len(filtered) > args.max_markets:
        filtered = filtered[: args.max_markets]

    derived = [derive(m) for m in filtered]
    anomalies = adjacent_day_anomalies(derived, threshold_pp=args.threshold_pp)

    # Write outputs
    md = render_markdown(derived, anomalies)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    md_path = os.path.join(out_dir, f"kyiv-strike-edge-{stamp}.md")
    js_path = os.path.join(out_dir, f"kyiv-strike-edge-{stamp}.json")

    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "event_slugs": slugs_list,
        "events_fetched": events_ok,
        "markets_total": len(markets),
        "markets_filtered": len(filtered),
        "derived": [asdict(x) for x in derived],
        "anomalies": anomalies,
    }

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(js_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(md_path)
    print(js_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
