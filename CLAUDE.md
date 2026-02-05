# Claude Code Context - Music Catalog Deal Pricer

## Project Overview

This is a Streamlit-based music catalog deal pricing application that helps labels evaluate potential artist deals. It calculates recommended investment amounts based on streaming data, deal structure, and target returns.

## Key Components

### Core Pricing Engine (`src/pricer/`)

- **model.py** - Main deal analysis engine with `CashFlowEngine` class
- **payback.py** - 18-month payback and IRR recommendation calculations
- **decay.py** - Genre-based decay curve loader from Excel
- **decay_weekly.py** - Weekly decay curve calculations
- **decay_curve.py** - Shifted decay curves for tracks post-peak

### Deal Analysis (`src/deal_analysis.py`)

High-level orchestrator that:
- Fetches track data from Snowflake
- Computes track-level decay (each track decays based on its release date)
- Calls the pricer engine with computed revenues

### App (`app.py`)

Streamlit frontend with artist search, deal configuration, and results display.

## Deal Type Mechanics (CRITICAL)

### 1. Royalty Deal (e.g., 80% label / 20% artist)

```
During Recoup: Label keeps 100% (their 80% + withholds artist's 20%)
After Recoup:  Label keeps 80%, Artist gets 20%
Recoup Rate:   Artist's royalty rate (20%)
```

- Recoupment is SLOW (at artist's royalty rate)
- But label keeps high % forever (80%)
- Best long-term deal for label

### 2. Funded Distribution (e.g., 30% label / 70% artist)

```
During Recoup: Label keeps 100% of gross
After Recoup:  Label keeps 30%, Artist gets 70%
Recoup Rate:   100% of gross
```

- Recoupment is FAST (100% of gross)
- Lower ongoing share (30%)
- Mid-tier deal for label

### 3. Profit Split (e.g., 50/50)

```
Step 1: Expenses reduce gross to net (Net = Gross - Expenses)
Step 2: Label recoups from net (100% until recouped)
Step 3: After recoup, split net 50/50
```

- Expenses PERMANENTLY destroy value
- Label recoups from smaller pie
- Weakest deal for label (for same terms)

### Expected Ranking (same revenue, target IRR)

```
Max Investment: Royalty > Distribution > Profit Split
```

## Key Calculations

### 18-Month Payback Recommendation

Maximum investment that can be recouped within 78 weeks. Varies by deal type:
- Royalty: ~20% of 78-week gross (recoup at artist royalty rate)
- Distribution: ~100% of 78-week gross (recoup at 100%)
- Profit Split: ~50% of 78-week gross (expenses reduce capacity)

### IRR Recommendation

Maximum investment that achieves target IRR (10% or 15%) over 10 years.
Uses binary search to find the investment where actual IRR = target IRR.

## Important Implementation Details

### Track-Level Decay Mode

When `use_track_level_decay=True`:
1. Each track decays individually based on `weeks_since_release`
2. Track-level calculation produces actual Year 1 revenue (with decay)
3. This Year 1 revenue is passed via `year1_revenue_override` to model.py
4. Do NOT recalculate Year 1 from `weekly × 52 × rate` (loses decay info)

### Recoupment in Weekly Cashflows

The `compute_weekly_cashflows()` function in payback.py handles deal-type-specific recoupment:
- Must pass `deal_type` parameter to get correct mechanics
- Royalty: Recoups at artist royalty rate
- Distribution: Recoups at 100% of gross
- Profit Split: Recoups at 100% of net (after expenses)

### Mid-Year Recoupment

When recoupment completes mid-year:
- Take the amount needed to finish recoup
- Split the remainder according to post-recoup terms
- Don't give label 100% of the whole year

## Common Issues & Fixes

### Issue: 18-month and 15% IRR nearly identical
**Cause**: Year 1 revenue being recalculated instead of using track-level value
**Fix**: Use `year1_revenue_override` when track-level decay is enabled

### Issue: Same recommendation for all deal types
**Cause**: `deal_type` not being passed to payback functions
**Fix**: Ensure `deal_type` parameter flows through all calculation functions

### Issue: IRR much higher than target
**Cause**: Using steady-state cash flows instead of actual cash flows with recoup
**Fix**: Binary search with deal-type-specific cash flow calculation

## Database

PostgreSQL on Render for persistent storage:
- `tracked_artists` - Artists being monitored
- `tracked_sounds` - TikTok sounds being tracked

## Deployment

- GitHub repo: `gio763/Stock-App`
- Hosted on Render (auto-deploys on push to main)
- Snowflake for streaming data
- Chartex API for TikTok data

## Testing

Run deal mechanics test:
```python
python -c "
from src.pricer.payback import compute_irr_recommendation, generate_weekly_gross_series, DealType

YEAR1 = 100000
DECAY = {1:1.0, 2:0.85, 3:0.72, 4:0.61, 5:0.52, 6:0.44, 7:0.37, 8:0.32, 9:0.27, 10:0.23}
weekly = generate_weekly_gross_series(YEAR1, DECAY, 10)
annual = [YEAR1 * DECAY[y] for y in range(1,11)]

for name, dt, pct in [('Royalty', DealType.ROYALTY, 0.80),
                       ('Distribution', DealType.DISTRIBUTION, 0.30),
                       ('Profit Split', DealType.PROFIT_SPLIT, 0.50)]:
    rec = compute_irr_recommendation(0.15, weekly, [g*pct for g in annual],
                                      pct, 0.70, False, dt, annual)
    print(f'{name}: \${rec.max_total_cost:,.0f}')
"
```

Expected output (roughly):
- Royalty: $316,000
- Distribution: $214,000
- Profit Split: $174,000
