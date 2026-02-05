# Kyiv Strike Edge Scanner

Local-only script to scan Polymarket Kyiv strike-related markets via the public Gamma API and produce a quick **signals/edge** report.

## What it does

- Discovers relevant **event slugs** (best-effort):
  - Scrapes the Ukraine category page for `kyiv` + `strike` event links
  - Optionally queries Gamma `events` with a few Kyiv strike search strings
- Pulls each event and flattens its `markets`
- Filters to Kyiv + (strike/attack/missile/drone/bomb) markets
- Computes derived fields per market:
  - `p_yes` from `outcomePrices`
  - `spread` from `bestAsk - bestBid` (when available)
  - `volume24hr`
  - `oneHourPriceChange` / `oneDayPriceChange`
  - rewards/incentives (best-effort; Gamma varies)
- Compares **adjacent days** (based on `endDate`) for "similar" questions and flags big probability gaps.

## Outputs

The script writes timestamped files to an output directory:
- `kyiv-strike-edge-YYYYMMDD-HHMMSS.md`
- `kyiv-strike-edge-YYYYMMDD-HHMMSS.json`

The JSON includes:
- discovered `event_slugs`
- counts fetched/filtered
- `derived` list (one item per market)
- `anomalies` list (adjacent-day diffs)

## How to run

From repo root:

```bash
python3 scripts/kyiv_strike_edge_scanner.py --out-dir memory/reports/kyiv-strike-edge
```

Useful knobs:

```bash
# cap work
python3 scripts/kyiv_strike_edge_scanner.py --max-events 80 --max-markets 400

# tighten/loosen anomaly flagging (percentage points)
python3 scripts/kyiv_strike_edge_scanner.py --threshold-pp 10

# if Gamma search params break, use page discovery only
python3 scripts/kyiv_strike_edge_scanner.py --no-search
```

## Notes / caveats

- Gamma API fields and query parameters can change.
- The adjacent-day comparison is heuristic: it normalizes the question text by stripping common date/time tokens.
- All metrics are informational only (not financial advice).
