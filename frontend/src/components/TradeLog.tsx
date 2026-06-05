import type { Trade } from "../types";
import { fmtDateTimeTz, tzAbbrev } from "../utils";

interface Props {
  trades: Trade[];
  timeZone?: string;
}

const fmt = (n: number, d = 2) =>
  n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export function TradeLog({ trades, timeZone = "UTC" }: Props) {
  if (trades.length === 0) {
    return <div className="trade-log empty">No trades were executed.</div>;
  }
  return (
    <div className="trade-log">
      <h3>Trades ({trades.length})</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time ({tzAbbrev(timeZone)})</th>
              <th>Action</th>
              <th>Side</th>
              <th>Symbol</th>
              <th className="num">Qty</th>
              <th className="num">Price</th>
              <th className="num">USD</th>
              <th className="num">Fee</th>
              <th className="num">PnL</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i}>
                <td className="mono">{fmtDateTimeTz(t.t, timeZone)}</td>
                <td>
                  <span className={`tag ${t.kind}`}>{t.kind}</span>
                  <span className="chain">{t.chain}</span>
                </td>
                <td>{t.side}</td>
                <td>{t.symbol}</td>
                <td className="num">{fmt(t.qty, 4)}</td>
                <td className="num">${fmt(t.price)}</td>
                <td className="num">${fmt(t.usd_value)}</td>
                <td className="num dim">${fmt(t.fee_usd)}</td>
                <td className={`num ${t.realized_pnl > 0 ? "pos" : t.realized_pnl < 0 ? "neg" : "dim"}`}>
                  {t.realized_pnl ? `$${fmt(t.realized_pnl)}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
