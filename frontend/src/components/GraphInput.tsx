import { useState } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  jsonError: string | null;
  compact?: boolean;
  collapsible?: boolean;
}

export function GraphInput({ value, onChange, jsonError, compact = false, collapsible = false }: Props) {
  const [open, setOpen] = useState(!collapsible);

  return (
    <div className="graph-input">
      <div className="graph-input-header">
        {collapsible ? (
          <button type="button" className="graph-toggle" onClick={() => setOpen((v) => !v)}>
            Strategy graph (JSON) {open ? "▾" : "▸"}
          </button>
        ) : (
          <span>Strategy graph (JSON)</span>
        )}
        {jsonError ? <span className="json-status bad">invalid JSON</span> : <span className="json-status ok">valid</span>}
      </div>
      {(!collapsible || open) && (
        <textarea
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={compact ? 10 : 20}
        />
      )}
    </div>
  );
}
