import type { Config } from "../App";
import type { ExampleGraph } from "../types";

interface Props {
  config: Config;
  onChange: (c: Config) => void;
  examples: ExampleGraph[];
  onSelectExample: (name: string) => void;
  onRun: () => void;
  loading: boolean;
  canRun: boolean;
}

const INTERVALS = ["15m", "1h", "4h", "1d"];

export function BacktestForm({ config, onChange, examples, onSelectExample, onRun, loading, canRun }: Props) {
  return (
    <div className="form">
      <label className="field">
        <span>Example strategy</span>
        <select defaultValue="" onChange={(e) => e.target.value && onSelectExample(e.target.value)}>
          <option value="">— load an example —</option>
          {examples.map((ex) => (
            <option key={ex.name} value={ex.name}>
              {ex.title}
            </option>
          ))}
        </select>
      </label>

      <div className="field-row">
        <label className="field">
          <span>Start</span>
          <input type="date" value={config.start} onChange={(e) => onChange({ ...config, start: e.target.value })} />
        </label>
        <label className="field">
          <span>End</span>
          <input type="date" value={config.end} onChange={(e) => onChange({ ...config, end: e.target.value })} />
        </label>
      </div>

      <div className="field-row">
        <label className="field">
          <span>Granularity</span>
          <select value={config.interval} onChange={(e) => onChange({ ...config, interval: e.target.value })}>
            {INTERVALS.map((i) => (
              <option key={i} value={i}>
                {i}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Initial capital (USD)</span>
          <input
            type="number"
            min={0}
            step={1000}
            value={config.initial_capital}
            onChange={(e) => onChange({ ...config, initial_capital: Number(e.target.value) })}
          />
        </label>
      </div>

      <button className="run-btn" onClick={onRun} disabled={loading || !canRun}>
        {loading ? "Running…" : "Run backtest"}
      </button>
    </div>
  );
}
