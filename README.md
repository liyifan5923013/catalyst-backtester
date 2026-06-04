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
  `candleSnapshot` (spot/perp candles) and `fundingHistory` (perp funding).

## What it supports

| Catalyst node | Backtest behavior |
| --- | --- |
| `action / swap` (EVM `base`) | DEX swap priced off Binance, flat gas + fee + slippage |
| `action / swap` (`hyperliquid`) | Spot order priced off Hyperliquid candles, taker fee + slippage |
| `action / perp_order` | Open / add / close Hyperliquid perp at leverage, with funding, mark-to-market PnL, and liquidation |
| `action / yield_deposit` / `yield_withdraw` | Aave-style deposit/withdraw accruing a flat configurable APY |
| `signal / price_threshold` | Boolean condition (`<` / `>`) evaluated each tick |

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
- USDC/USDT/DAI are treated as a $1 peg.
- Yield uses a flat configurable APY (default 5%) rather than live historical
  Aave rates.

## Tests

```bash
cd backend
pytest -q
```

Tests cover graph parsing, execution math, and a synthetic-data run of all 15
example graphs (no network required).
