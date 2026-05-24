# Prediction Markets KPI Dashboard

Streamlit dashboard for comparing prediction market liquidity and participation across `Kalshi`, `Polymarket`, and `Opinion`.

## KPIs

The app provides three KPI views via the sidebar selector:

1. **KPI 1 - Open Interest Market Share**
   - Daily open-interest share by platform (area chart)
   - Absolute open interest by platform
   - Includes anomaly handling for zero OI with positive volume (linear interpolation + audit table)

2. **KPI 2 - Volume / Open Interest**
   - 7-day rolling `notional_volume_usd / open_interest_usd` ratio by platform

3. **KPI 3 - Slippage Ladder**
   - Live orderbook-based slippage curve by execution size (log-scale x-axis)
   - Market focus: 2028 Democratic nominee market

## Data Sources

- Historical merged market data (KPI 1/2 base): hosted CSV by Paradigm Predictions
- Opinion for KPI 1/2: Dune query (`DUNE_API_KEY` required)
- Live orderbooks for KPI 3:
  - Kalshi market ticker: `KXPRESNOMD-28-GN`
  - Polymarket YES token ID: `54533043819946592547517511176940999955633860128497669742211153063842200957669`
  - Opinion orderbook endpoint

## Project Structure

```text
.
├── app.py
├── dashboard/
│   ├── __init__.py
│   ├── constants.py
│   ├── kpi_views.py
│   ├── market_data.py
│   ├── models.py
│   └── orderbooks.py
├── requirements.txt
└── README.md
```

## Setup

1. Create a virtual environment:
   - `python3 -m venv .venv`
2. Activate it:
   - `source .venv/bin/activate`
3. Install dependencies:
   - `pip install -r requirements.txt`
4. Add environment variables in `.env` (optional but recommended):
   - `DUNE_API_KEY=your_key_here`

## Run

- Standard:
  - `streamlit run app.py`
- Without activating venv:
  - `./.venv/bin/streamlit run app.py --server.port 8501 --server.headless true`

## Behavior Notes

- `Refresh data` clears Streamlit cache.
- KPI 1/2 still render without Dune Opinion data; Opinion overlay is shown only when Dune fetch succeeds.
- KPI 3 uses live orderbooks and computes average slippage across YES and NO sides.
