#!/usr/bin/env python3
"""Kyiv Strike Markets Dashboard Generator

Fetches Kyiv strike markets from Gamma API and generates a standalone HTML dashboard
with all data embedded (works when opened directly via file:// with no CORS issues).

Usage:
    python generate_dashboard.py
    python generate_dashboard.py --refresh  # Re-run and regenerate

Output: dashboard/kyiv_dashboard.html
"""

import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import argparse

import requests

# Configuration
UKRAINE_PAGE = "https://polymarket.com/geopolitics/ukraine"
GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "kyiv_dashboard.html")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (OpenClaw Kyiv Dashboard)"})


@dataclass
class Market:
    """Represents a Kyiv strike market."""
    id: str
    title: str
    question: str
    date_str: str
    display_date: str
    date_iso: str
    probability: float
    best_bid: float
    best_ask: float
    spread: float
    spread_percent: float
    volume_24h: float
    change_1h: float
    change_24h: float
    liquidity: float
    slug: str
    closed: bool
    accepting_orders: bool
    url: str
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _get(url: str, *, timeout: int = 30) -> requests.Response:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def extract_slugs_from_page(html: str) -> List[str]:
    """Extract event slugs from the Ukraine page HTML."""
    lower = html.lower()
    cuts = []
    for needle in ("<footer", "contentinfo", "adventure one qss"):
        i = lower.find(needle)
        if i != -1:
            cuts.append(i)
    if cuts:
        html = html[:min(cuts)]

    candidates: Set[str] = set()
    for m in re.finditer(r'href="/event/([^"/?#]+)(?:/([^"?#]+))?', html):
        ev = m.group(1)
        mk = m.group(2)
        if ev and ev != "live":
            candidates.add(ev)
        if mk and mk != "live":
            candidates.add(mk)
    
    # Filter to Kyiv-related slugs
    kyiv_slugs = [s for s in candidates if "kyiv" in s.lower() or "kiev" in s.lower()]
    return sorted(kyiv_slugs)


def gamma_event_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch event data by slug from Gamma API."""
    r = _get(f"{GAMMA_EVENTS}?slug={slug}", timeout=25)
    js = r.json()
    if not js:
        return None
    return js[0]


def gamma_market_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch market data by slug from Gamma API."""
    r = _get(f"{GAMMA_MARKETS}?slug={slug}", timeout=20)
    js = r.json()
    if not js:
        return None
    return js[0]


def discover_kyiv_event_slugs() -> List[str]:
    """Discover Kyiv strike event slugs from the Ukraine page and known patterns."""
    # Try to discover from page
    try:
        html = _get(UKRAINE_PAGE, timeout=40).text
        discovered = extract_slugs_from_page(html)
        print(f"  Discovered {len(discovered)} Kyiv slugs from Ukraine page")
    except Exception as e:
        print(f"  Warning: Could not fetch Ukraine page: {e}")
        discovered = []
    
    # Known event slugs for Kyiv strikes (seed list)
    known_slugs = [
        "russia-strike-on-kyiv-municipality-on-252",
        "russia-strike-on-kyiv-municipality-on-253",
        "russia-strike-on-kyiv-by-221",
        "russia-strike-on-kyiv-by-222",
        "will-russia-strike-kyiv",
        "kyiv-airstrike-",
    ]
    
    # Try to find variations by searching markets
    try:
        # Search for Kyiv-related markets
        search_terms = ["kyiv", "kiev", "strike"]
        for term in search_terms:
            try:
                r = _get(f"{GAMMA_MARKETS}?limit=100&search={term}", timeout=30)
                results = r.json()
                for m in results:
                    slug = m.get("slug", "")
                    q = m.get("question", "").lower()
                    if "kyiv" in q or "kiev" in q or "kyiv" in slug.lower():
                        if "strike" in q or "strike" in slug.lower():
                            if slug and slug not in known_slugs:
                                known_slugs.append(slug)
            except Exception:
                pass
    except Exception as e:
        print(f"  Warning: Market search failed: {e}")
    
    # Merge discovered and known
    all_slugs = list(set(discovered + known_slugs))
    return sorted(all_slugs)


def parse_date_from_title(title: str, year: int = None) -> Tuple[str, str, datetime]:
    """Parse date from group item title like 'February 5'."""
    if year is None:
        year = datetime.now().year
    
    month_map = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    
    # Try to parse "February 5" format
    parts = title.lower().split()
    if len(parts) >= 2:
        month = month_map.get(parts[0])
        day = re.search(r'(\d+)', parts[1])
        if month and day:
            try:
                dt = datetime(year, month, int(day.group(1)))
                return title, dt.strftime('%Y-%m-%d'), dt
            except ValueError:
                pass
    
    # Fallback
    now = datetime.now()
    return title, now.strftime('%Y-%m-%d'), now


def parse_market_data(market: Dict[str, Any]) -> Optional[Market]:
    """Parse raw market data from Gamma API into Market object."""
    try:
        # Parse outcomePrices - returns array like ["0.15", "0.85"] for [Yes, No]
        yes_price = 0.0
        outcome_prices = market.get("outcomePrices")
        if isinstance(outcome_prices, str):
            try:
                prices = json.loads(outcome_prices)
                if isinstance(prices, list) and len(prices) > 0:
                    yes_price = float(prices[0])
            except json.JSONDecodeError:
                pass
        elif isinstance(outcome_prices, list) and len(outcome_prices) > 0:
            yes_price = float(outcome_prices[0])
        
        # Calculate spread from bestBid and bestAsk
        best_bid = float(market.get("bestBid", 0) or 0)
        best_ask = float(market.get("bestAsk", 0) or 0)
        spread = best_ask - best_bid
        spread_percent = (spread / best_ask * 100) if best_ask > 0 else 0
        
        # Extract date from groupItemTitle
        date_title = market.get("groupItemTitle", "Unknown")
        display_date, date_iso, date_obj = parse_date_from_title(date_title)
        
        # Get volume and changes
        volume_24h = float(market.get("volume24hr", 0) or 0)
        change_1h = float(market.get("oneHourPriceChange", 0) or 0)
        change_24h = float(market.get("oneDayPriceChange", 0) or 0)
        
        return Market(
            id=str(market.get("id", "")),
            title=market.get("question", date_title),
            question=market.get("question", ""),
            date_str=date_title,
            display_date=display_date,
            date_iso=date_iso,
            probability=yes_price,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            spread_percent=round(spread_percent, 2),
            volume_24h=volume_24h,
            change_1h=change_1h * 100,  # Convert to percentage
            change_24h=change_24h * 100,  # Convert to percentage
            liquidity=float(market.get("liquidityNum", 0) or 0),
            slug=market.get("slug", ""),
            closed=bool(market.get("closed", False)),
            accepting_orders=bool(market.get("acceptingOrders", True)),
            url=f"https://polymarket.com/event/{market.get('slug', '')}"
        )
    except Exception as e:
        print(f"    Warning: Failed to parse market: {e}")
        return None


def fetch_kyiv_markets() -> List[Market]:
    """Fetch all Kyiv strike markets from Gamma API."""
    print("Fetching Kyiv strike markets...")
    
    # Discover event slugs
    event_slugs = discover_kyiv_event_slugs()
    print(f"  Found {len(event_slugs)} potential event slugs")
    
    markets: List[Market] = []
    seen_ids: Set[str] = set()
    
    # Fetch markets from each event
    for slug in event_slugs:
        try:
            print(f"  Fetching event: {slug[:50]}...")
            event = gamma_event_by_slug(slug)
            if not event:
                continue
            
            event_markets = event.get("markets", [])
            print(f"    Event has {len(event_markets)} markets")
            
            for m in event_markets:
                market_id = str(m.get("id", ""))
                if not market_id or market_id in seen_ids:
                    continue
                
                # Verify it's Kyiv + strike related
                q = (m.get("question") or "").lower()
                s = (m.get("slug") or "").lower()
                
                if ("kyiv" in q or "kyiv" in s or "kiev" in q or "kiev" in s):
                    if "strike" in q or "strike" in s or "attack" in q:
                        parsed = parse_market_data(m)
                        if parsed:
                            markets.append(parsed)
                            seen_ids.add(market_id)
                            print(f"      Added: {parsed.display_date} ({parsed.probability:.1%})")
        except Exception as e:
            print(f"    Warning: Error fetching event {slug}: {e}")
    
    # Also try searching for individual markets
    try:
        print("  Searching for individual markets...")
        search_terms = ["kyiv strike", "kyiv attack", "russia strike kyiv"]
        for term in search_terms:
            try:
                r = _get(f"{GAMMA_MARKETS}?limit=50&search={term}", timeout=20)
                results = r.json()
                for m in results:
                    market_id = str(m.get("id", ""))
                    if market_id in seen_ids:
                        continue
                    
                    q = (m.get("question") or "").lower()
                    s = (m.get("slug") or "").lower()
                    
                    if ("kyiv" in q or "kyiv" in s or "kiev" in q or "kiev" in s):
                        if "strike" in q or "strike" in s or "attack" in q:
                            parsed = parse_market_data(m)
                            if parsed:
                                markets.append(parsed)
                                seen_ids.add(market_id)
                                print(f"    Found via search: {parsed.display_date}")
            except Exception as e:
                print(f"    Warning: Search failed for '{term}': {e}")
    except Exception as e:
        print(f"  Warning: Market search error: {e}")
    
    print(f"  Total unique markets: {len(markets)}")
    return markets


def calculate_summary(markets: List[Market]) -> Dict[str, Any]:
    """Calculate summary statistics for the markets."""
    active_markets = [m for m in markets if not m.closed or m.probability > 0]
    
    if not markets:
        return {
            "total_markets": 0,
            "avg_probability": 0,
            "total_volume_24h": 0,
            "avg_spread": 0,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    total_prob = sum(m.probability for m in active_markets)
    total_vol = sum(m.volume_24h for m in markets)
    total_spread = sum(m.spread_percent for m in active_markets)
    
    return {
        "total_markets": len(active_markets),
        "avg_probability": round((total_prob / len(active_markets)) * 100, 1) if active_markets else 0,
        "total_volume_24h": round(total_vol, 2),
        "avg_spread": round(total_spread / len(active_markets), 2) if active_markets else 0,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }


def detect_anomalies(markets: List[Market]) -> List[Dict[str, Any]]:
    """Detect anomalies in market data."""
    anomalies = []
    
    # Sort by date for comparison
    sorted_markets = sorted(markets, key=lambda m: m.date_iso)
    
    for i, current in enumerate(sorted_markets):
        prev = sorted_markets[i - 1] if i > 0 else None
        
        if current.closed and current.probability == 0:
            continue
        
        # Check for inverted probabilities
        if prev and current.probability < prev.probability * 0.7 and not current.closed:
            anomalies.append({
                "type": "probability-inversion",
                "severity": "medium",
                "market": current.to_dict(),
                "related_market": prev.to_dict(),
                "description": f"Significant probability drop from {prev.probability:.1%} to {current.probability:.1%} despite later date",
                "metric": f"{((prev.probability - current.probability) * 100):.1f}% gap"
            })
        
        # Check for unusual spikes
        if prev and current.probability > prev.probability * 1.5 and not current.closed:
            anomalies.append({
                "type": "probability-spike",
                "severity": "high",
                "market": current.to_dict(),
                "related_market": prev.to_dict(),
                "description": f"Unusual probability spike from {prev.probability:.1%} to {current.probability:.1%}",
                "metric": f"+{((current.probability - prev.probability) * 100):.1f}%"
            })
        
        # Check for wide spreads
        if current.spread_percent > 10 and not current.closed:
            anomalies.append({
                "type": "wide-spread",
                "severity": "low",
                "market": current.to_dict(),
                "description": "Wide bid-ask spread indicates low liquidity",
                "metric": f"{current.spread_percent}% spread"
            })
        
        # Check for high volume with low probability
        if current.volume_24h > 10000 and current.probability < 0.1 and not current.closed:
            anomalies.append({
                "type": "volume-anomaly",
                "severity": "medium",
                "market": current.to_dict(),
                "description": "High trading volume on low-probability event",
                "metric": f"${current.volume_24h:,.0f} volume"
            })
        
        # Check for rapid price changes
        if abs(current.change_1h) > 10 and not current.closed:
            anomalies.append({
                "type": "rapid-change",
                "severity": "high" if abs(current.change_1h) > 20 else "medium",
                "market": current.to_dict(),
                "description": f"Rapid {'increase' if current.change_1h > 0 else 'decrease'} in the last hour",
                "metric": f"{current.change_1h:+.1f}%"
            })
    
    return anomalies[:8]  # Limit to top 8


def generate_html(markets: List[Market], summary: Dict[str, Any], anomalies: List[Dict[str, Any]]) -> str:
    """Generate the standalone HTML dashboard with embedded data."""
    
    # Serialize data to JSON for embedding
    markets_json = json.dumps([m.to_dict() for m in markets], ensure_ascii=False)
    summary_json = json.dumps(summary, ensure_ascii=False)
    anomalies_json = json.dumps(anomalies, ensure_ascii=False)
    
    generated_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kyiv Strike Markets Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        :root {{
            --bg-primary: #0d1117;
            --bg-secondary: #161b22;
            --bg-tertiary: #21262d;
            --bg-card: #1c2128;
            --text-primary: #e6edf3;
            --text-secondary: #8b949e;
            --text-muted: #6e7681;
            --accent-primary: #58a6ff;
            --accent-secondary: #79c0ff;
            --success: #3fb950;
            --success-dim: #238636;
            --danger: #f85149;
            --danger-dim: #da3633;
            --warning: #d29922;
            --warning-dim: #9e6a03;
            --border-color: #30363d;
            --shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }}

        .header {{
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 2rem;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: var(--shadow);
        }}

        .header-content {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}

        .header-title {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .header-title i {{
            color: var(--accent-primary);
            font-size: 1.5rem;
        }}

        .header-title h1 {{
            font-size: 1.5rem;
            font-weight: 600;
            background: linear-gradient(90deg, var(--accent-primary), var(--accent-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        .header-meta {{
            display: flex;
            align-items: center;
            gap: 1.5rem;
            flex-wrap: wrap;
        }}

        .last-update {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }}

        .refresh-status {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .refresh-indicator {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
        }}

        .refresh-btn {{
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            transition: all 0.2s;
            text-decoration: none;
        }}

        .refresh-btn:hover {{
            background: var(--border-color);
        }}

        .refresh-btn.loading i {{
            animation: spin 1s linear infinite;
        }}

        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}

        .main-content {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        .summary-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .summary-card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow);
        }}

        .summary-label {{
            color: var(--text-secondary);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}

        .summary-value {{
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}

        .summary-delta {{
            font-size: 0.875rem;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }}

        .summary-delta.positive {{ color: var(--success); }}
        .summary-delta.negative {{ color: var(--danger); }}

        .section {{
            margin-bottom: 2rem;
        }}

        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
            flex-wrap: wrap;
            gap: 1rem;
        }}

        .section-title {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.25rem;
            font-weight: 600;
        }}

        .section-title i {{
            color: var(--accent-primary);
        }}

        .markets-container {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
        }}

        .markets-table {{
            width: 100%;
            border-collapse: collapse;
        }}

        .markets-table th {{
            background: var(--bg-tertiary);
            padding: 1rem;
            text-align: left;
            font-weight: 500;
            color: var(--text-secondary);
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            cursor: pointer;
            user-select: none;
        }}

        .markets-table th i {{
            margin-left: 0.25rem;
            font-size: 0.625rem;
        }}

        .markets-table td {{
            padding: 1rem;
            border-top: 1px solid var(--border-color);
            vertical-align: middle;
        }}

        .markets-table tr:hover {{
            background: rgba(88, 166, 255, 0.05);
        }}

        .market-name {{
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}

        .market-name .name {{
            font-weight: 500;
            color: var(--text-primary);
        }}

        .market-name .date {{
            font-size: 0.75rem;
            color: var(--text-secondary);
        }}

        .market-name .tag {{
            display: inline-block;
            font-size: 0.625rem;
            padding: 0.125rem 0.375rem;
            background: var(--accent-primary);
            color: var(--bg-primary);
            border-radius: 4px;
            margin-top: 0.25rem;
            width: fit-content;
        }}

        .market-name .tag.closed {{
            background: var(--danger-dim);
            color: var(--danger);
        }}

        .price-display {{
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}

        .price-main {{
            font-size: 1.125rem;
            font-weight: 600;
        }}

        .price-spread {{
            font-size: 0.75rem;
            color: var(--text-secondary);
        }}

        .change-indicator {{
            display: flex;
            align-items: center;
            gap: 0.375rem;
            font-weight: 500;
        }}

        .change-indicator.positive {{ color: var(--success); }}
        .change-indicator.negative {{ color: var(--danger); }}
        .change-indicator.neutral {{ color: var(--text-secondary); }}

        .volume-display {{
            color: var(--text-secondary);
            font-size: 0.875rem;
        }}

        .anomalies-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 1rem;
        }}

        .anomaly-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            border-left: 4px solid var(--warning);
        }}

        .anomaly-card.critical {{ border-left-color: var(--danger); }}
        .anomaly-card.opportunity {{ border-left-color: var(--success); }}

        .anomaly-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.75rem;
        }}

        .anomaly-type {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.75rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--warning);
        }}

        .anomaly-card.critical .anomaly-type {{ color: var(--danger); }}
        .anomaly-card.opportunity .anomaly-type {{ color: var(--success); }}

        .anomaly-severity {{
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.625rem;
            font-weight: 600;
            text-transform: uppercase;
            background: var(--warning-dim);
            color: var(--warning);
        }}

        .anomaly-card.critical .anomaly-severity {{
            background: var(--danger-dim);
            color: var(--danger);
        }}

        .anomaly-card.opportunity .anomaly-severity {{
            background: var(--success-dim);
            color: var(--success);
        }}

        .anomaly-title {{
            font-weight: 500;
            margin-bottom: 0.5rem;
        }}

        .anomaly-details {{
            color: var(--text-secondary);
            font-size: 0.875rem;
            line-height: 1.5;
        }}

        .anomaly-metric {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            font-family: 'SF Mono', Monaco, monospace;
            background: var(--bg-tertiary);
            padding: 0.125rem 0.375rem;
            border-radius: 4px;
            margin: 0 0.125rem;
        }}

        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 1.5rem;
        }}

        .chart-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
        }}

        .chart-header {{
            margin-bottom: 1rem;
        }}

        .chart-title {{
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-primary);
        }}

        .chart-container {{
            position: relative;
            height: 250px;
        }}

        .empty-state {{
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
        }}

        .empty-state i {{
            font-size: 3rem;
            margin-bottom: 1rem;
            color: var(--text-muted);
        }}

        .empty-state h3 {{
            font-size: 1.125rem;
            margin-bottom: 0.5rem;
            color: var(--text-primary);
        }}

        .footer {{
            text-align: center;
            padding: 2rem;
            color: var(--text-muted);
            font-size: 0.75rem;
            border-top: 1px solid var(--border-color);
            margin-top: 2rem;
        }}

        .python-notice {{
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            color: var(--text-secondary);
            font-size: 0.875rem;
        }}

        .python-notice code {{
            background: var(--bg-primary);
            padding: 0.125rem 0.375rem;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, monospace;
            color: var(--accent-primary);
        }}

        @media (max-width: 768px) {{
            .header-content {{
                flex-direction: column;
                align-items: flex-start;
            }}
            .main-content {{
                padding: 1rem;
            }}
            .markets-table {{
                font-size: 0.875rem;
            }}
            .markets-table th,
            .markets-table td {{
                padding: 0.75rem 0.5rem;
            }}
            .charts-grid {{
                grid-template-columns: 1fr;
            }}
            .anomalies-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}

        ::-webkit-scrollbar-track {{
            background: var(--bg-secondary);
        }}

        ::-webkit-scrollbar-thumb {{
            background: var(--border-color);
            border-radius: 4px;
        }}

        ::-webkit-scrollbar-thumb:hover {{
            background: var(--text-muted);
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="header-title">
                <i class="fas fa-crosshairs"></i>
                <h1>Kyiv Strike Markets Dashboard</h1>
            </div>
            <div class="header-meta">
                <div class="last-update">
                    <i class="fas fa-clock"></i>
                    <span id="lastUpdate">{generated_time}</span>
                </div>
                <div class="refresh-status">
                    <div class="refresh-indicator"></div>
                    <span>Data Embedded</span>
                </div>
                <a href="#" class="refresh-btn" onclick="location.reload()">
                    <i class="fas fa-sync-alt"></i>
                    <span>Reload Page</span>
                </a>
            </div>
        </div>
    </header>

    <main class="main-content">
        <div class="python-notice">
            <i class="fas fa-info-circle"></i> 
            This dashboard contains <strong>embedded data</strong> from the Gamma API. 
            To refresh with live data, run: <code>python generate_dashboard.py</code>
        </div>
        
        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="summary-card">
                <div class="summary-label">Active Markets</div>
                <div class="summary-value" id="totalMarkets">--</div>
                <div class="summary-delta positive">
                    <i class="fas fa-chart-line"></i>
                    <span>Live data</span>
                </div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Avg Probability</div>
                <div class="summary-value" id="avgProbability">--</div>
                <div class="summary-delta neutral">
                    <i class="fas fa-minus"></i>
                    <span>24h change</span>
                </div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Total Volume (24h)</div>
                <div class="summary-value" id="totalVolume">--</div>
                <div class="summary-delta positive">
                    <i class="fas fa-arrow-up"></i>
                    <span>Trading activity</span>
                </div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Avg Spread</div>
                <div class="summary-value" id="avgSpread">--</div>
                <div class="summary-delta neutral">
                    <i class="fas fa-compress-arrows-alt"></i>
                    <span>Bid-Ask spread</span>
                </div>
            </div>
        </div>

        <!-- Markets Section -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">
                    <i class="fas fa-list"></i>
                    Strike Markets
                </h2>
            </div>
            <div class="markets-container">
                <table class="markets-table">
                    <thead>
                        <tr>
                            <th onclick="sortMarkets('date')">Date <i class="fas fa-sort"></i></th>
                            <th onclick="sortMarkets('probability')">Probability <i class="fas fa-sort"></i></th>
                            <th onclick="sortMarkets('spread')">Spread <i class="fas fa-sort"></i></th>
                            <th onclick="sortMarkets('volume')">Volume (24h) <i class="fas fa-sort"></i></th>
                            <th onclick="sortMarkets('change1h')">1h Change <i class="fas fa-sort"></i></th>
                            <th onclick="sortMarkets('change24h')">24h Change <i class="fas fa-sort"></i></th>
                        </tr>
                    </thead>
                    <tbody id="marketsTableBody">
                    </tbody>
                </table>
            </div>
        </section>

        <!-- Anomalies Section -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">
                    <i class="fas fa-exclamation-triangle"></i>
                    Anomaly Detection
                </h2>
            </div>
            <div class="anomalies-grid" id="anomaliesContainer">
            </div>
        </section>

        <!-- Charts Section -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">
                    <i class="fas fa-chart-bar"></i>
                    Market Analytics
                </h2>
            </div>
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-header">
                        <div class="chart-title">Probability Trend by Date</div>
                    </div>
                    <div class="chart-container">
                        <canvas id="probabilityChart"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <div class="chart-header">
                        <div class="chart-title">Volume Distribution</div>
                    </div>
                    <div class="chart-container">
                        <canvas id="volumeChart"></canvas>
                    </div>
                </div>
            </div>
        </section>
    </main>

    <footer class="footer">
        <p>Kyiv Strike Markets Dashboard • Data from Polymarket Gamma API • Generated at {generated_time}</p>
        <p><a href="https://polymarket.com/geopolitics/ukraine" target="_blank" style="color: var(--accent-primary);">View on Polymarket</a></p>
    </footer>

    <script>
        // Embedded Data (no external API calls needed)
        const EMBEDDED_MARKETS = {markets_json};
        const EMBEDDED_SUMMARY = {summary_json};
        const EMBEDDED_ANOMALIES = {anomalies_json};
        
        // State
        let sortColumn = 'date';
        let sortDirection = 'asc';
        let charts = {{}};

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {{
            initializeDashboard();
        }});

        function initializeDashboard() {{
            updateSummary();
            renderMarketsTable();
            renderAnomalies();
            renderCharts();
        }}

        function updateSummary() {{
            const s = EMBEDDED_SUMMARY;
            document.getElementById('totalMarkets').textContent = s.total_markets;
            document.getElementById('avgProbability').textContent = s.avg_probability + '%';
            document.getElementById('totalVolume').textContent = '$' + (s.total_volume_24h / 1000).toFixed(1) + 'k';
            document.getElementById('avgSpread').textContent = s.avg_spread + '%';
        }}

        function renderMarketsTable() {{
            const tbody = document.getElementById('marketsTableBody');
            const sorted = sortData([...EMBEDDED_MARKETS]);
            
            if (sorted.length === 0) {{
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="empty-state">
                            <i class="fas fa-inbox"></i>
                            <h3>No markets found</h3>
                        </td>
                    </tr>
                `;
                return;
            }}
            
            tbody.innerHTML = sorted.map(m => {{
                const probClass = m.probability > 0.5 ? 'positive' : m.probability < 0.2 ? 'negative' : 'neutral';
                const change1hClass = m.change_1h > 0 ? 'positive' : m.change_1h < 0 ? 'negative' : 'neutral';
                const change24hClass = m.change_24h > 0 ? 'positive' : m.change_24h < 0 ? 'negative' : 'neutral';
                const statusTag = m.closed ? '<span class="tag closed">Closed</span>' : '';
                
                return `
                    <tr>
                        <td>
                            <div class="market-name">
                                <span class="name">${{m.display_date}}</span>
                                <span class="date">${{formatRelativeDate(m.date_iso)}}</span>
                                ${{statusTag}}
                            </div>
                        </td>
                        <td>
                            <div class="price-display">
                                <span class="price-main ${{probClass}}">${{(m.probability * 100).toFixed(1)}}%</span>
                                <span class="price-spread">${{(m.best_bid * 100).toFixed(1)}}¢ - ${{(m.best_ask * 100).toFixed(1)}}¢</span>
                            </div>
                        </td>
                        <td>
                            <span class="change-indicator ${{m.spread_percent < 5 ? 'positive' : m.spread_percent > 15 ? 'negative' : 'neutral'}}">
                                ${{m.spread_percent}}%
                            </span>
                        </td>
                        <td>
                            <span class="volume-display">$${{m.volume_24h.toLocaleString()}}</span>
                        </td>
                        <td>
                            <span class="change-indicator ${{change1hClass}}">
                                <i class="fas fa-${{m.change_1h > 0 ? 'arrow-up' : m.change_1h < 0 ? 'arrow-down' : 'minus'}}"></i>
                                ${{Math.abs(m.change_1h).toFixed(1)}}%
                            </span>
                        </td>
                        <td>
                            <span class="change-indicator ${{change24hClass}}">
                                <i class="fas fa-${{m.change_24h > 0 ? 'arrow-up' : m.change_24h < 0 ? 'arrow-down' : 'minus'}}"></i>
                                ${{Math.abs(m.change_24h).toFixed(1)}}%
                            </span>
                        </td>
                    </tr>
                `;
            }}).join('');
        }}

        function renderAnomalies() {{
            const container = document.getElementById('anomaliesContainer');
            
            if (EMBEDDED_ANOMALIES.length === 0) {{
                container.innerHTML = `
                    <div class="empty-state">
                        <i class="fas fa-check-circle"></i>
                        <h3>No anomalies detected</h3>
                        <p>All markets appear to be pricing normally</p>
                    </div>
                `;
                return;
            }}
            
            const typeLabels = {{
                'probability-inversion': 'Price Inversion',
                'probability-spike': 'Price Spike',
                'wide-spread': 'Low Liquidity',
                'volume-anomaly': 'Volume Anomaly',
                'rapid-change': 'Rapid Movement'
            }};
            
            const typeIcons = {{
                'probability-inversion': 'fa-exchange-alt',
                'probability-spike': 'fa-bolt',
                'wide-spread': 'fa-water',
                'volume-anomaly': 'fa-chart-bar',
                'rapid-change': 'fa-tachometer-alt'
            }};
            
            container.innerHTML = EMBEDDED_ANOMALIES.map(a => `
                <div class="anomaly-card ${{a.severity === 'high' ? 'critical' : a.type === 'probability-inversion' ? 'opportunity' : ''}}">
                    <div class="anomaly-header">
                        <div class="anomaly-type">
                            <i class="fas ${{typeIcons[a.type] || 'fa-exclamation'}}"></i>
                            ${{typeLabels[a.type] || a.type}}
                        </div>
                        <div class="anomaly-severity">${{a.severity}}</div>
                    </div>
                    <div class="anomaly-title">${{a.market.display_date}}</div>
                    <div class="anomaly-details">
                        ${{a.description}}
                        <br>
                        <span class="anomaly-metric">
                            <i class="fas fa-hashtag"></i>
                            ${{a.metric}}
                        </span>
                    </div>
                </div>
            `).join('');
        }}

        function renderCharts() {{
            renderProbabilityChart();
            renderVolumeChart();
        }}

        function renderProbabilityChart() {{
            const ctx = document.getElementById('probabilityChart').getContext('2d');
            
            if (charts.probability) {{
                charts.probability.destroy();
            }}
            
            const activeMarkets = EMBEDDED_MARKETS.filter(m => !m.closed || m.probability > 0);
            const sorted = [...activeMarkets].sort((a, b) => new Date(a.date_iso) - new Date(b.date_iso)).slice(0, 14);
            const labels = sorted.map(m => m.display_date);
            const data = sorted.map(m => (m.probability * 100).toFixed(1));
            
            charts.probability = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Probability (%)',
                        data: data,
                        borderColor: '#58a6ff',
                        backgroundColor: 'rgba(88, 166, 255, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 4,
                        pointBackgroundColor: '#58a6ff',
                        pointBorderColor: '#0d1117',
                        pointBorderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ color: '#30363d' }},
                            ticks: {{ color: '#8b949e' }}
                        }},
                        y: {{
                            grid: {{ color: '#30363d' }},
                            ticks: {{ color: '#8b949e', callback: v => v + '%' }},
                            min: 0,
                            max: 100
                        }}
                    }}
                }}
            }});
        }}

        function renderVolumeChart() {{
            const ctx = document.getElementById('volumeChart').getContext('2d');
            
            if (charts.volume) {{
                charts.volume.destroy();
            }}
            
            const activeMarkets = EMBEDDED_MARKETS.filter(m => !m.closed || m.probability > 0);
            const sorted = [...activeMarkets].sort((a, b) => new Date(a.date_iso) - new Date(b.date_iso)).slice(0, 14);
            const labels = sorted.map(m => m.display_date);
            const data = sorted.map(m => (m.volume_24h / 1000).toFixed(1));
            
            charts.volume = new Chart(ctx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Volume ($k)',
                        data: data,
                        backgroundColor: sorted.map(m => {{
                            const c = m.change_24h;
                            return c > 0 ? 'rgba(63, 185, 80, 0.7)' : c < 0 ? 'rgba(248, 81, 73, 0.7)' : 'rgba(139, 148, 158, 0.7)';
                        }}),
                        borderRadius: 4,
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ color: '#8b949e' }}
                        }},
                        y: {{
                            grid: {{ color: '#30363d' }},
                            ticks: {{ color: '#8b949e', callback: v => '$' + v + 'k' }}
                        }}
                    }}
                }}
            }});
        }}

        function sortMarkets(column) {{
            if (sortColumn === column) {{
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            }} else {{
                sortColumn = column;
                sortDirection = 'asc';
            }}
            renderMarketsTable();
        }}

        function sortData(data) {{
            return [...data].sort((a, b) => {{
                let aVal, bVal;
                switch (sortColumn) {{
                    case 'date': aVal = a.date_iso; bVal = b.date_iso; break;
                    case 'probability': aVal = a.probability; bVal = b.probability; break;
                    case 'spread': aVal = a.spread_percent; bVal = b.spread_percent; break;
                    case 'volume': aVal = a.volume_24h; bVal = b.volume_24h; break;
                    case 'change1h': aVal = a.change_1h; bVal = b.change_1h; break;
                    case 'change24h': aVal = a.change_24h; bVal = b.change_24h; break;
                    default: return 0;
                }}
                return sortDirection === 'asc' ? (aVal > bVal ? 1 : -1) : (aVal < bVal ? 1 : -1);
            }});
        }}

        function formatRelativeDate(dateStr) {{
            const now = new Date();
            now.setHours(0, 0, 0, 0);
            const target = new Date(dateStr);
            target.setHours(0, 0, 0, 0);
            const diff = Math.floor((target - now) / (1000 * 60 * 60 * 24));
            if (diff === 0) return 'Today';
            if (diff === 1) return 'Tomorrow';
            if (diff > 1 && diff < 7) return `In ${{diff}} days`;
            if (diff >= 7 && diff < 14) return 'Next week';
            if (diff < 0 && diff > -7) return `${{Math.abs(diff)}} days ago`;
            if (diff <= -7) return 'Past';
            return 'Future';
        }}
    </script>
</body>
</html>
'''
    return html


def main():
    parser = argparse.ArgumentParser(description="Generate Kyiv Strike Markets Dashboard")
    parser.add_argument("--refresh", action="store_true", help="Force refresh and regenerate")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Kyiv Strike Markets Dashboard Generator")
    print("=" * 60)
    
    # Fetch markets
    markets = fetch_kyiv_markets()
    
    if not markets:
        print("\nERROR: No markets found!")
        print("This could mean:")
        print("  - No Kyiv strike markets are currently active")
        print("  - The API structure has changed")
        print("  - Network connectivity issues")
        return 1
    
    # Calculate summary
    summary = calculate_summary(markets)
    print(f"\nSummary:")
    print(f"  Active Markets: {summary['total_markets']}")
    print(f"  Avg Probability: {summary['avg_probability']}%")
    print(f"  Total Volume (24h): ${summary['total_volume_24h']:,.2f}")
    print(f"  Avg Spread: {summary['avg_spread']}%")
    
    # Detect anomalies
    anomalies = detect_anomalies(markets)
    print(f"\nAnomalies Detected: {len(anomalies)}")
    for a in anomalies:
        print(f"  - {a['type']}: {a['market']['display_date']} ({a['severity']})")
    
    # Generate HTML
    print("\nGenerating HTML...")
    html = generate_html(markets, summary, anomalies)
    
    # Write to file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"\n✓ Dashboard saved to: {OUTPUT_FILE}")
    print(f"  File size: {len(html):,} bytes")
    print(f"\nOpen this file in your browser to view the dashboard.")
    print(f"To refresh data, run: python generate_dashboard.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
