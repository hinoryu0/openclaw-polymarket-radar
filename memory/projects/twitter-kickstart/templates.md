# Templates

## 1) "Radar ping" (single market)

**Hook:**
- `Radar ping: {MARKET} moved fast.`

**Data line:**
- `p(YES): {PCT}% | Δ1h: {DELTA1H}pp | Δ24h: {DELTA24H}pp | vol24h: ${VOL}`

**Context (1–2 lines):**
- `What this market is pricing: {ONE_SENTENCE}`
- `My read: {HYPOTHESIS} (not advice)`

**What to watch:**
- `Watch for: {TRIGGER_1}, {TRIGGER_2}`

**Link:**
- `{URL}`

---

## 2) "Adjacent-day anomaly" (term structure)

- `Interesting term structure on {TOPIC}:` 
- `{DATE_A}: {PCT_A}% vs {DATE_B}: {PCT_B}% (Δ {DIFF}pp)`
- `If the event risk is mostly "continuous", why the gap? Possible explanations:`
  - `1) {EXPLANATION}`
  - `2) {EXPLANATION}`
- `I’ll monitor for: {DATA_POINT}`
- `{URL_A} / {URL_B}`

---

## 3) "3-market heatmap" (mini dashboard)

- `Polymarket Ukraine radar (last {WINDOW}):`
  - `1) {MKT1} — {PCT1}% (Δ24h {D1}pp) vol {V1}`
  - `2) {MKT2} — {PCT2}% (Δ24h {D2}pp) vol {V2}`
  - `3) {MKT3} — {PCT3}% (Δ24h {D3}pp) vol {V3}`
- `Theme: {ONE_LINE_SUMMARY}`
- `What I'm watching next: {NEXT}`

---

## 4) "How I think" (process tweet)

- `How I evaluate an "edge" on prediction markets:`
  - `1) Liquidity/volume: can I enter/exit without donating spread?`
  - `2) Spread: is the market wide?`
  - `3) Newsflow cadence: is the next update scheduled or random?`
  - `4) Term structure: do nearby dates make sense together?`
  - `5) Position sizing: assume I'm wrong.`

---

## 5) "Mispricing checklist" (copy/paste)

- `Mispricing checklist:`
  - `□ Did the market move on *old* news?`
  - `□ Are there two markets implying contradictory probabilities?`
  - `□ Is vol high but spread still wide (market makers pulling)?`
  - `□ Are adjacent days wildly different?`
  - `□ Is resolution criteria ambiguous?`

---

## 6) Replies to drive engagement (without spam)

- `Do you have a better explanation for {OBSERVATION}?`
- `If you're tracking a different market that matches this newsflow, drop it.`
- `What would change your view on this one?`
