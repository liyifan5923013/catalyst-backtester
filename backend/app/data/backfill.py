"""CLI to pre-warm the persistence layer with candles and/or funding.

Examples
--------
Pre-warm Binance ETH 1h candles into the store::

    DATABASE_URL=postgresql://... \
        python -m app.data.backfill --source binance --symbol ETH \
        --interval 1h --start 2024-01-01 --end 2025-01-01

Pre-warm Hyperliquid ETH funding history::

    DATABASE_URL=postgresql://... \
        python -m app.data.backfill --source hyperliquid --symbol ETH \
        --funding --start 2024-01-01 --end 2025-01-01

Runs through the same read-through repository as live backtests, so it only
fetches the gaps that are not already stored.
"""
from __future__ import annotations

import argparse
import sys

from . import db
from .providers import INTERVAL_MS, BinanceProvider, EquityProvider, HyperliquidProvider, to_ms


def _parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m app.data.backfill", description=__doc__)
    p.add_argument("--source", choices=["binance", "hyperliquid", "yahoo"], required=True)
    p.add_argument("--symbol", required=True, help="Asset symbol, e.g. ETH or AAPL")
    p.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS), help="Candle interval")
    p.add_argument("--start", required=True, help="ISO date/datetime (UTC)")
    p.add_argument("--end", required=True, help="ISO date/datetime (UTC)")
    p.add_argument(
        "--funding",
        action="store_true",
        help="Backfill funding history instead of candles (hyperliquid only)",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not db.is_enabled():
        print(
            "DATABASE_URL is not set; nothing to backfill. "
            "Set DATABASE_URL to a Postgres/Timescale instance and retry.",
            file=sys.stderr,
        )
        return 2

    start_ms, end_ms = to_ms(args.start), to_ms(args.end)
    if end_ms <= start_ms:
        print("--end must be after --start", file=sys.stderr)
        return 2

    if args.funding:
        if args.source != "hyperliquid":
            print("--funding is only supported for --source hyperliquid", file=sys.stderr)
            return 2
        df = HyperliquidProvider().fetch_funding(args.symbol, start_ms, end_ms)
        print(f"funding {args.symbol} [{args.start} -> {args.end}]: {len(df)} rows in store")
        return 0

    if args.source == "binance":
        df = BinanceProvider().fetch(args.symbol, args.interval, start_ms, end_ms)
    elif args.source == "yahoo":
        df = EquityProvider().fetch(args.symbol, args.interval, start_ms, end_ms)
    else:
        df = HyperliquidProvider().fetch_candles(args.symbol, args.interval, start_ms, end_ms)
    print(
        f"candles {args.source}:{args.symbol} {args.interval} "
        f"[{args.start} -> {args.end}]: {len(df)} rows in store"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
