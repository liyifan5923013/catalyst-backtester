interface Props {
  value: string;
  onChange: (v: string) => void;
  jsonError: string | null;
}

export function GraphInput({ value, onChange, jsonError }: Props) {
  return (
    <div className="graph-input">
      <div className="graph-input-header">
        <span>Strategy graph (JSON)</span>
        {jsonError ? <span className="json-status bad">invalid JSON</span> : <span className="json-status ok">valid</span>}
      </div>
      <textarea
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={20}
      />
    </div>
  );
}
