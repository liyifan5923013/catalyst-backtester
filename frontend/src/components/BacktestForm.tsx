import { useState } from "react";
import type { Config } from "../App";
import type { ExampleGraph } from "../types";
import {
  COMPARE_LABELS,
  effectiveCompareRange,
  type CompareMode,
  type CompareState,
} from "../utils";

interface Props {
  config: Config;
  onChange: (c: Config) => void;
  examples: ExampleGraph[];
  onSelectExample: (name: string) => void;
  onRun: () => void;
  loading: boolean;
  canRun: boolean;
  compare: CompareState;
  onCompareChange: (c: CompareState) => void;
  onShare: () => string;
  hideRunButton?: boolean;
}

const INTERVALS = ["15m", "1h", "4h", "1d"];

const MODES: { id: CompareMode; label: string; hint: string }[] = [
  { id: "previous", label: "Previous period", hint: "Immediately preceding window of equal length (period-over-period)" },
  { id: "yoy", label: "Year-over-year", hint: "Same calendar window one year earlier" },
  { id: "custom", label: "Custom", hint: "Pick any comparison range" },
];

export function BacktestForm({
  config,
  onChange,
  examples,
  onSelectExample,
  onRun,
  loading,
  canRun,
  compare,
  onCompareChange,
  onShare,
  hideRunButton = false,
}: Props) {
  const cmpRange = effectiveCompareRange(config, compare);
  const [copied, setCopied] = useState(false);

  async function handleShareClick() {
    const url = onShare();
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch {
        /* clipboard unavailable; URL is already in the address bar */
      }
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

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

      <div className="field-group">
        <div className="field-group-head">
          <span>Analysis period</span>
          <span className="tz-badge" title="All dates and times are interpreted and displayed in UTC.">
            UTC
          </span>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Start</span>
            <input
              className="date-input"
              type="date"
              value={config.start}
              onChange={(e) => onChange({ ...config, start: e.target.value })}
            />
          </label>
          <label className="field">
            <span>End</span>
            <input
              className="date-input"
              type="date"
              value={config.end}
              onChange={(e) => onChange({ ...config, end: e.target.value })}
            />
          </label>
        </div>
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

      <div className="field-group">
        <label className="compare-toggle">
          <input
            type="checkbox"
            checked={compare.enabled}
            onChange={(e) => onCompareChange({ ...compare, enabled: e.target.checked })}
          />
          <span>Compare to another period</span>
        </label>

        {compare.enabled && (
          <div className="compare-body">
            <div className="seg">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  title={m.hint}
                  className={`seg-btn ${compare.mode === m.id ? "active" : ""}`}
                  onClick={() => onCompareChange({ ...compare, mode: m.id })}
                >
                  {m.label}
                </button>
              ))}
            </div>

            <div className="field-row">
              <label className="field">
                <span>Compare start</span>
                <input
                  className="date-input"
                  type="date"
                  value={compare.mode === "custom" ? compare.start : cmpRange.start}
                  disabled={compare.mode !== "custom"}
                  onChange={(e) => onCompareChange({ ...compare, start: e.target.value })}
                />
              </label>
              <label className="field">
                <span>Compare end</span>
                <input
                  className="date-input"
                  type="date"
                  value={compare.mode === "custom" ? compare.end : cmpRange.end}
                  disabled={compare.mode !== "custom"}
                  onChange={(e) => onCompareChange({ ...compare, end: e.target.value })}
                />
              </label>
            </div>
            <p className="compare-hint">
              Comparing against the <strong>{COMPARE_LABELS[compare.mode]}</strong> ({cmpRange.start} → {cmpRange.end}, UTC).
            </p>
          </div>
        )}
      </div>

      {!hideRunButton && (
        <button className="run-btn" onClick={onRun} disabled={loading || !canRun}>
          {loading ? "Running…" : compare.enabled ? "Run & compare" : "Run backtest"}
        </button>
      )}

      <button type="button" className="share-btn" onClick={handleShareClick}>
        {copied ? "Copied!" : "Copy share link"}
      </button>
    </div>
  );
}
