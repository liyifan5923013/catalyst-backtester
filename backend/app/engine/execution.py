"""Action executors: swap / spot, perp, and yield.

Each executor mutates the :class:`Portfolio` and returns an
:class:`ExecResult` (an optional trade record plus any events). Insufficient
balance or margin never raises; it records a ``warning`` event and skips, so a
backtest never fails silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..models import CostModel, Event, Node, Trade
from ..data.equity_providers import EQUITY_CHAINS
from .portfolio import STABLES, PerpPosition, Portfolio, YieldPosition

BPS = 1e4


@dataclass
class ExecContext:
    ts_iso: str
    # execution price for (symbol, chain)
    price: Callable[[str, str], float]


@dataclass
class ExecResult:
    trade: Optional[Trade] = None
    events: List[Event] = field(default_factory=list)


def _parse_amount(value, all_value: float) -> float:
    if isinstance(value, str) and value.strip().lower() in ("all", "max"):
        return all_value
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid numeric amount: {value!r}")


def _warn(ts_iso: str, node_id: str, message: str) -> ExecResult:
    return ExecResult(trade=None, events=[Event(t=ts_iso, level="warning", node_id=node_id, message=message)])


# ---------------------------------------------------------------------------
# Swap / spot
# ---------------------------------------------------------------------------
def execute_swap(node: Node, pf: Portfolio, costs: CostModel, ctx: ExecContext) -> ExecResult:
    cfg = node.config
    frm = str(cfg.get("from_asset", "")).upper()
    to = str(cfg.get("to_asset", "")).upper()
    chain = str(cfg.get("chain", "base")).lower()
    is_hl = chain == "hyperliquid"
    is_equity = chain in EQUITY_CHAINS

    if is_equity:
        fee_bps = costs.equity_commission_bps
        slip_bps = costs.equity_slippage_bps
        gas = 0.0
    elif is_hl:
        fee_bps = costs.hl_taker_fee_bps
        slip_bps = costs.hl_slippage_bps
        gas = 0.0
    else:
        fee_bps = costs.evm_swap_fee_bps
        slip_bps = costs.evm_slippage_bps
        gas = costs.evm_gas_usd

    buying = frm in STABLES and to not in STABLES
    selling = frm not in STABLES and to in STABLES
    if not (buying or selling):
        return _warn(ctx.ts_iso, node.id, f"Unsupported swap {frm}->{to}; only USDC<->token is supported.")

    token = to if buying else frm
    price = ctx.price(token, chain)
    if price <= 0:
        return _warn(ctx.ts_iso, node.id, f"No valid price for {token} on {chain}.")

    if buying:
        usd_in = _parse_amount(cfg.get("amount"), pf.get(frm))
        if usd_in <= 0:
            return _warn(ctx.ts_iso, node.id, "Swap amount resolved to 0.")
        if pf.get(frm) < usd_in + gas:
            return _warn(
                ctx.ts_iso, node.id,
                f"Insufficient {frm}: need ${usd_in + gas:.2f}, have ${pf.get(frm):.2f}.",
            )
        fee = usd_in * fee_bps / BPS
        slip = usd_in * slip_bps / BPS
        tokens_out = (usd_in - fee - slip) / price
        pf.sub(frm, usd_in + gas)
        # Cost basis includes everything paid (notional + fees + gas).
        pf.buy_spot(to, tokens_out, usd_in + gas)
        trade = Trade(
            t=ctx.ts_iso, node_id=node.id, kind="swap", chain=chain, symbol=token, side="buy",
            qty=tokens_out, price=price, usd_value=usd_in, fee_usd=fee + slip + gas,
            note=f"Bought {tokens_out:.6f} {token} for ${usd_in:.2f}",
        )
        return ExecResult(trade=trade)

    # selling token -> stablecoin
    qty = _parse_amount(cfg.get("amount"), pf.get(frm))
    if qty <= 0:
        return _warn(ctx.ts_iso, node.id, "Swap amount resolved to 0.")
    if pf.get(frm) < qty - 1e-12:
        return _warn(
            ctx.ts_iso, node.id,
            f"Insufficient {frm}: need {qty:.6f}, have {pf.get(frm):.6f}.",
        )
    gross = qty * price
    fee = gross * fee_bps / BPS
    slip = gross * slip_bps / BPS
    usd_out = gross - fee - slip - gas
    realized = pf.sell_spot(frm, qty, usd_out)
    pf.add(to, usd_out)
    trade = Trade(
        t=ctx.ts_iso, node_id=node.id, kind="swap", chain=chain, symbol=token, side="sell",
        qty=qty, price=price, usd_value=gross, fee_usd=fee + slip + gas, realized_pnl=realized,
        note=f"Sold {qty:.6f} {token} for ${usd_out:.2f} (pnl ${realized:.2f})",
    )
    return ExecResult(trade=trade)


# ---------------------------------------------------------------------------
# Perps (Hyperliquid)
# ---------------------------------------------------------------------------
def execute_perp(node: Node, pf: Portfolio, costs: CostModel, ctx: ExecContext) -> ExecResult:
    cfg = node.config
    symbol = str(cfg.get("symbol", "")).upper()
    chain = str(cfg.get("chain", "hyperliquid")).lower()
    side = str(cfg.get("side", "")).lower()  # long | short
    reduce_only = bool(cfg.get("reduce_only", False))
    price = ctx.price(symbol, chain)
    if price <= 0:
        return _warn(ctx.ts_iso, node.id, f"No valid price for perp {symbol}.")

    pos = pf.perps.get(symbol)

    if reduce_only:
        if pos is None or abs(pos.size_tokens) < 1e-12:
            return _warn(ctx.ts_iso, node.id, f"reduce_only order but no open {symbol} position.")
        notional_full = abs(pos.size_tokens) * price
        # "all"/"max" closes the whole position.
        size_usd = _parse_amount(cfg.get("size_usd"), notional_full)
        if size_usd <= 0:
            return _warn(ctx.ts_iso, node.id, "Perp size_usd resolved to 0.")
        fee = size_usd * costs.hl_taker_fee_bps / BPS
        close_tokens = min(size_usd / price, abs(pos.size_tokens))
        # Snap away sub-$1 dust so round-trips fully close.
        if (abs(pos.size_tokens) - close_tokens) * price < 1.0:
            close_tokens = abs(pos.size_tokens)
        sign = 1.0 if pos.size_tokens > 0 else -1.0
        realized = sign * close_tokens * (price - pos.entry_price)
        frac = close_tokens / abs(pos.size_tokens)
        released_margin = pos.margin * frac
        if pf.get(pf.cash_asset) < fee:
            fee = 0.0  # let fees be netted from proceeds if cash is short
        pf.add(pf.cash_asset, released_margin + realized - fee)
        pos.size_tokens -= sign * close_tokens
        pos.margin -= released_margin
        if abs(pos.size_tokens) < 1e-9:
            pf.perps.pop(symbol, None)
        trade = Trade(
            t=ctx.ts_iso, node_id=node.id, kind="perp_close", chain=chain, symbol=symbol, side=side,
            qty=close_tokens, price=price, usd_value=close_tokens * price, fee_usd=fee,
            realized_pnl=realized,
            note=f"Closed {close_tokens:.6f} {symbol} (pnl ${realized:.2f})",
        )
        return ExecResult(trade=trade)

    # opening / adding
    size_usd = _parse_amount(cfg.get("size_usd"), 0.0)
    if size_usd <= 0:
        return _warn(ctx.ts_iso, node.id, "Perp size_usd resolved to 0.")
    fee = size_usd * costs.hl_taker_fee_bps / BPS
    try:
        leverage = float(cfg.get("leverage", 1) or 1)
    except (TypeError, ValueError):
        return _warn(ctx.ts_iso, node.id, f"Invalid leverage: {cfg.get('leverage')!r}.")
    if leverage <= 0:
        return _warn(ctx.ts_iso, node.id, f"Leverage must be > 0 (got {leverage}).")
    if side not in ("long", "short"):
        return _warn(ctx.ts_iso, node.id, f"Perp side must be 'long' or 'short' (got {side!r}).")
    margin_required = size_usd / leverage
    if pf.get(pf.cash_asset) < margin_required + fee:
        return _warn(
            ctx.ts_iso, node.id,
            f"Insufficient margin: need ${margin_required + fee:.2f}, have ${pf.get(pf.cash_asset):.2f}.",
        )
    signed_tokens = (size_usd / price) * (1.0 if side == "long" else -1.0)
    pf.sub(pf.cash_asset, margin_required + fee)

    if pos is None or abs(pos.size_tokens) < 1e-12:
        pf.perps[symbol] = PerpPosition(
            symbol=symbol, size_tokens=signed_tokens, entry_price=price,
            margin=margin_required, leverage=leverage,
        )
    elif (pos.size_tokens > 0) == (signed_tokens > 0):
        # same direction: weighted-average entry, aggregate margin
        old_abs = abs(pos.size_tokens)
        new_abs = abs(signed_tokens)
        pos.entry_price = (old_abs * pos.entry_price + new_abs * price) / (old_abs + new_abs)
        pos.size_tokens += signed_tokens
        pos.margin += margin_required
        pos.leverage = (abs(pos.size_tokens) * pos.entry_price) / pos.margin if pos.margin else leverage
    else:
        # opposite direction without reduce_only: net it down / flip
        pos.size_tokens += signed_tokens
        pos.margin += margin_required
        if abs(pos.size_tokens) < 1e-9:
            pf.perps.pop(symbol, None)
        else:
            pos.entry_price = price
    trade = Trade(
        t=ctx.ts_iso, node_id=node.id, kind="perp_open", chain=chain, symbol=symbol, side=side,
        qty=abs(signed_tokens), price=price, usd_value=size_usd, fee_usd=fee,
        note=f"Opened {side} {symbol} ${size_usd:.0f} @ {leverage:g}x",
    )
    return ExecResult(trade=trade)


# ---------------------------------------------------------------------------
# Yield (EVM, e.g. Aave)
# ---------------------------------------------------------------------------
def execute_yield(node: Node, pf: Portfolio, costs: CostModel, ctx: ExecContext) -> ExecResult:
    cfg = node.config
    chain = str(cfg.get("chain", "base")).lower()
    protocol = str(cfg.get("protocol", "aave"))
    pool = str(cfg.get("pool", ""))
    asset = str(cfg.get("asset", "USDC")).upper()
    key = f"{protocol}:{pool}:{asset}"
    gas = 0.0 if chain == "hyperliquid" else costs.evm_gas_usd

    if node.subtype == "yield_deposit":
        amount = _parse_amount(cfg.get("amount"), pf.get(asset))
        if amount <= 0:
            return _warn(ctx.ts_iso, node.id, "Yield deposit amount resolved to 0.")
        if pf.get(asset) < amount + gas:
            return _warn(
                ctx.ts_iso, node.id,
                f"Insufficient {asset} to deposit: need ${amount + gas:.2f}, have ${pf.get(asset):.2f}.",
            )
        pf.sub(asset, amount + gas)
        existing = pf.yields.get(key)
        if existing is None:
            pf.yields[key] = YieldPosition(key=key, asset=asset, principal=amount, apy=costs.yield_apy)
        else:
            existing.principal += amount
        trade = Trade(
            t=ctx.ts_iso, node_id=node.id, kind="yield_deposit", chain=chain, symbol=asset,
            side="deposit", qty=amount, price=1.0, usd_value=amount, fee_usd=gas,
            note=f"Deposited ${amount:.2f} {asset} into {protocol}",
        )
        return ExecResult(trade=trade)

    # yield_withdraw
    pos = pf.yields.get(key)
    if pos is None or pos.principal <= 0:
        return _warn(ctx.ts_iso, node.id, f"No {asset} position in {protocol} to withdraw.")
    amount = _parse_amount(cfg.get("amount"), pos.principal)
    amount = min(amount, pos.principal)
    if amount <= 0:
        return _warn(ctx.ts_iso, node.id, "Yield withdraw amount resolved to 0.")
    pos.principal -= amount
    payout = max(amount - gas, 0.0)
    pf.add(asset, payout)
    if pos.principal <= 1e-9:
        pf.yields.pop(key, None)
    trade = Trade(
        t=ctx.ts_iso, node_id=node.id, kind="yield_withdraw", chain=chain, symbol=asset,
        side="withdraw", qty=amount, price=1.0, usd_value=amount, fee_usd=gas,
        note=f"Withdrew ${amount:.2f} {asset} from {protocol}",
    )
    return ExecResult(trade=trade)


def apply_funding(pf: Portfolio, symbol: str, rate: float, price: float, ts_iso: str) -> List[Event]:
    """Apply an 8h funding payment to an open perp position.

    Longs pay shorts when the rate is positive. The payment is charged to the
    position's margin.
    """
    pos = pf.perps.get(symbol)
    if pos is None or abs(pos.size_tokens) < 1e-12:
        return []
    sign = 1.0 if pos.size_tokens > 0 else -1.0
    payment = sign * rate * pos.notional(price)  # cost to the position
    pos.margin -= payment
    return []


def check_liquidations(
    pf: Portfolio, price_of, maintenance_frac: float, ts_iso: str
) -> tuple[List[Event], List[Trade]]:
    """Liquidate any perp whose equity falls below maintenance margin.

    Returns both the warning events and synthetic close trades so the trade log
    and PnL reconcile on liquidated runs.
    """
    events: List[Event] = []
    trades: List[Trade] = []
    for symbol in list(pf.perps.keys()):
        pos = pf.perps[symbol]
        price = price_of(symbol)
        if pos.equity(price) <= maintenance_frac * pos.notional(price):
            is_long = pos.size_tokens > 0
            realized = pos.unrealized_pnl(price)
            events.append(Event(
                t=ts_iso, level="warning", node_id=None,
                message=f"Liquidated {symbol} {'long' if is_long else 'short'} "
                        f"position at ${price:.2f} (margin wiped out).",
            ))
            trades.append(Trade(
                t=ts_iso, node_id="liquidation", kind="perp_close", chain="hyperliquid",
                symbol=symbol, side="short" if is_long else "long",
                qty=abs(pos.size_tokens), price=price, usd_value=pos.notional(price),
                fee_usd=0.0, realized_pnl=realized,
                note=f"Liquidated {'long' if is_long else 'short'} (lost margin ${pos.margin:.2f})",
            ))
            pf.perps.pop(symbol, None)
    return events, trades
