---
title: Catalyst Backtester
emoji: "\U0001F4C8"
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Catalyst Backtesting Engine

A backtesting website that ingests **Catalyst strategy graphs**, replays them
tick-by-tick against real historical market data, and reports how the strategy
would have performed over a chosen time period.

- **Backend:** Python / FastAPI + pandas
- **Frontend:** React + TypeScript (Vite) + Recharts
- **Data (free, public):** Binance klines (EVM spot pricing), Hyperliquid
  `candleSnapshot` (spot/perp candles) and `fundingHistory` (perp funding), and
  **US equities** via Yahoo Finance (no key) with optional Alpha Vantage fallback
  (`ALPHA_VANTAGE_API_KEY`).

## What it supports

| Catalyst node | Backtest behavior |
| --- | --- |
| `action / swap` (EVM `base`) | DEX swap priced off Binance, flat gas + fee + slippage |
| `action / swap` (`hyperliquid`) | Spot order priced off Hyperliquid candles, taker fee + slippage |
| `action / swap` (`equity`) | US stock buy/sell (e.g. AAPL) priced off Yahoo Finance, commission + slippage |
| `action / perp_order` | Open / add / close Hyperliquid perp at leverage, with funding, mark-to-market PnL, and liquidation |
| `action / yield_deposit` / `yield_withdraw` | Aave-style deposit/withdraw accruing a flat configurable APY |
| `signal / price_threshold` | Boolean condition (`<` / `>`) evaluated each tick. Set `"market": "equity"` for stock prices. |

Options, prediction markets, etc. are intentionally out of scope.

## Graph semantics (how a strategy runs)

- An **action with no incoming edge** runs **once at t0** (the strategy's
  starting position).
- A **`signal -> action`** edge fires the action on a **rising edge**
  (condition flips false to true), then **re-arms** once the condition goes
  back to false. This is what makes the "repeating ladder / round trip"
  strategies (graphs 4, 7, 12, 13) actually repeat instead of firing every tick.
- An **`action -> action`** edge runs the downstream action immediately after
  the upstream one (a sequential chain, fired once).
- `"enabled": false` nodes are skipped.

## Modeling decisions (MVP)

- **Granularity / tick rate:** you choose the interval (`15m`, `1h`, `4h`,
  `1d`); one candle = one tick. Signals are evaluated every tick.
- **Fills:** at the candle close, no latency modeling.
- **Costs:** flat per-venue gas / fee / slippage (all configurable).
- **Failed transactions:** insufficient balance/margin skips the action and
  records a `warning` event (nothing fails silently). Perp positions can be
  liquidated.
- **Initial portfolio:** configurable, default **$10,000 USDC**.
- `amount` for a buy (`from USDC`) is **USD notional**; for a sell
  (`to USDC`) it is **token quantity** (or `"all"`).

## Running it

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs at http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend.

### Run a backtest from the CLI

```bash
cd backend
python -m app.run_example examples/graph_12.json --start 2024-01-01 --end 2024-06-01 --interval 1h
```

### Optional: TimescaleDB persistence

By default fetched data is cached to parquet under `backend/.cache/`. For a real
persistence layer, set `DATABASE_URL` to a Postgres/TimescaleDB instance and the
providers switch to a **read-through store** that fetches only missing time gaps and
reuses every candle across overlapping ranges. If `DATABASE_URL` is unset, everything
falls back to the parquet cache (so the hosted demo is unaffected).

```bash
# Bring up Timescale + the app locally
docker compose up --build         # app on http://localhost:7860

# Or point an existing app at a managed Timescale and run migrations
cd backend
export DATABASE_URL=postgresql://user:pass@host:5432/catalyst
alembic upgrade head

# Pre-warm (backfill) data into the store
python -m app.data.backfill --source binance --symbol ETH --interval 1h \
    --start 2024-01-01 --end 2025-01-01
python -m app.data.backfill --source hyperliquid --symbol ETH --funding \
    --start 2024-01-01 --end 2025-01-01
```

## API

`POST /api/backtest`

```jsonc
{
  "graph": { /* Catalyst graph */ },
  "start": "2024-01-01",
  "end": "2024-06-01",
  "interval": "1h",
  "initial_capital": 10000
}
```

Returns `{ metrics, equity_curve, trades, events }`.

## Data notes / limitations

- The primary Binance API geo-blocks some regions (HTTP 451), so the provider
  automatically falls back to `data-api.binance.vision`, then `api.binance.us`.
- Hyperliquid's `candleSnapshot` only serves the **most recent ~5000 candles**
  per market, so deep history isn't available there. When an HL-specific price
  series is missing for the requested range, the engine **falls back to the
  Binance (EVM) price** as a proxy, and perp funding is simply skipped. For the
  highest-fidelity perp/funding backtests, use a recent date range. The
  frontend defaults to the **last 120 days** for this reason.
- **US equities:** Yahoo Finance chart API (free, no key). Optional
  `ALPHA_VANTAGE_API_KEY` for Alpha Vantage free tier (25 req/day). Use
  `"chain": "equity"` on swap actions (e.g. buy AAPL with USDC).
- USDC/USDT/DAI are treated as a $1 peg.
- Yield uses a flat configurable APY (default 5%) rather than live historical
  Aave rates.

## Tests

```bash
cd backend
pytest -q
```

Tests cover graph parsing, execution math, a synthetic-data run of all example
graphs, equity provider parsing, and the persistence layer's gap/coverage/staleness logic (no
network required). The Timescale read-through round-trip test runs only when
`DATABASE_URL` is set; otherwise it is skipped.
