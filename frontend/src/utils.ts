// Small date + formatting helpers. All dates are plain ISO "YYYY-MM-DD" strings
// interpreted in UTC, matching the backend (which works entirely in UTC).

export interface Range {
  start: string;
  end: string;
}

function toUTC(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

function fromUTC(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function dayCount(start: string, end: string): number {
  const ms = toUTC(end).getTime() - toUTC(start).getTime();
  return Math.max(1, Math.round(ms / 86_400_000));
}

/** Immediately preceding window of equal length (环比 / period-over-period). */
export function previousPeriod({ start, end }: Range): Range {
  const len = dayCount(start, end);
  const newEnd = start;
  const newStart = fromUTC(new Date(toUTC(start).getTime() - len * 86_400_000));
  return { start: newStart, end: newEnd };
}

/** Same calendar window one year earlier (同比 / year-over-year). */
export function yearOverYear({ start, end }: Range): Range {
  const s = toUTC(start);
  const e = toUTC(end);
  s.setUTCFullYear(s.getUTCFullYear() - 1);
  e.setUTCFullYear(e.getUTCFullYear() - 1);
  return { start: fromUTC(s), end: fromUTC(e) };
}

/** A short human description of a strategy graph for the AI summary prompt. */
export function describeGraph(graph: unknown): string {
  try {
    const nodes = (graph as { nodes?: Array<{ kind?: string; subtype?: string; enabled?: boolean }> }).nodes ?? [];
    const counts = new Map<string, number>();
    for (const n of nodes) {
      if (n.enabled === false) continue;
      const key = n.subtype || n.kind || "node";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    if (counts.size === 0) return "An empty strategy graph.";
    const parts = [...counts.entries()].map(([k, v]) => `${v} ${k}${v > 1 ? "s" : ""}`);
    return `A strategy graph with ${parts.join(", ")}.`;
  } catch {
    return "A Catalyst strategy graph.";
  }
}

export type CompareMode = "previous" | "yoy" | "custom";

export interface CompareState {
  enabled: boolean;
  mode: CompareMode;
  start: string; // used when mode === "custom"
  end: string;
}

export const COMPARE_LABELS: Record<CompareMode, string> = {
  previous: "previous period",
  yoy: "same period last year",
  custom: "custom comparison",
};

/** Resolve the comparison range that will actually be backtested. */
export function effectiveCompareRange(primary: Range, c: CompareState): Range {
  if (c.mode === "previous") return previousPeriod(primary);
  if (c.mode === "yoy") return yearOverYear(primary);
  return { start: c.start, end: c.end };
}

export const fmtMoney = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export const fmtPct = (n: number, signed = true) =>
  `${signed && n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
