// Small date + formatting helpers. All dates are plain ISO "YYYY-MM-DD" strings
// interpreted in UTC, matching the backend (which works entirely in UTC).

import type { Config } from "./App";

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

// -- Display time zones -------------------------------------------------------
// Backend timestamps are UTC. These control only how result times are rendered;
// the analysis-period date inputs remain UTC calendar dates.

export const TIME_ZONES: { id: string; label: string }[] = [
  { id: "UTC", label: "UTC" },
  { id: "local", label: "Local (browser)" },
  { id: "America/Los_Angeles", label: "Los Angeles (Pacific)" },
  { id: "America/Denver", label: "Denver (Mountain)" },
  { id: "America/Chicago", label: "Chicago (Central)" },
  { id: "America/New_York", label: "New York (Eastern)" },
  { id: "America/Sao_Paulo", label: "São Paulo" },
  { id: "Europe/London", label: "London" },
  { id: "Europe/Berlin", label: "Berlin / Paris" },
  { id: "Europe/Moscow", label: "Moscow" },
  { id: "Asia/Dubai", label: "Dubai" },
  { id: "Asia/Kolkata", label: "Mumbai / Kolkata" },
  { id: "Asia/Singapore", label: "Singapore" },
  { id: "Asia/Shanghai", label: "Shanghai / Beijing" },
  { id: "Asia/Tokyo", label: "Tokyo" },
  { id: "Australia/Sydney", label: "Sydney" },
];

/** Resolve the special "local" id to the browser's IANA zone. */
export function resolveTz(tz: string): string {
  if (tz === "local") {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      return "UTC";
    }
  }
  return tz || "UTC";
}

/** Offset in ms (zone wall-clock − actual UTC) for `instant` in `timeZone`. */
function tzOffsetMs(instant: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(instant);
  const m: Record<string, string> = {};
  for (const p of parts) m[p.type] = p.value;
  const hour = m.hour === "24" ? "00" : m.hour;
  const asUtc = Date.UTC(+m.year, +m.month - 1, +m.day, +hour, +m.minute, +m.second);
  return asUtc - instant.getTime();
}

/**
 * UTC ISO instant for local midnight of a YYYY-MM-DD date in the given zone.
 * Used so the analysis-period dates mean midnight in the chosen display zone
 * (the backend parses tz-aware ISO and converts to UTC). For UTC this is just
 * "<date>T00:00:00.000Z", matching prior behavior.
 */
export function zonedDateToUtcIso(dateStr: string, tz: string): string {
  const [y, mo, d] = dateStr.split("-").map(Number);
  if (!y || !mo || !d) return dateStr;
  const zone = resolveTz(tz);
  const guess = Date.UTC(y, mo - 1, d, 0, 0, 0);
  const offset = tzOffsetMs(new Date(guess), zone);
  let real = guess - offset;
  // Refine once to handle DST boundaries where the offset shifts.
  const offset2 = tzOffsetMs(new Date(real), zone);
  if (offset2 !== offset) real = guess - offset2;
  return new Date(real).toISOString();
}

/** Parse a (UTC) backend timestamp that may lack a zone suffix. */
export function parseUtc(iso: string): Date {
  let s = iso.trim().replace(" ", "T");
  if (!/[zZ]$/.test(s) && !/[+-]\d{2}:?\d{2}$/.test(s)) s += "Z";
  return new Date(s);
}

/** Short time-zone abbreviation for labels, e.g. "UTC", "PST", "GMT+8". */
export function tzAbbrev(tz: string, ref: Date = new Date()): string {
  const zone = resolveTz(tz);
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      timeZoneName: "short",
    }).formatToParts(ref);
    return parts.find((p) => p.type === "timeZoneName")?.value ?? zone;
  } catch {
    return "UTC";
  }
}

/** Short "Mon D" date in the given zone (for chart axis ticks). */
export function fmtDateTz(iso: string, tz: string): string {
  const d = parseUtc(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: resolveTz(tz),
      month: "short",
      day: "numeric",
    }).format(d);
  } catch {
    return iso;
  }
}

/** Full "Mon D, YYYY HH:MM" in the given zone (24h) for tooltips/tables. */
export function fmtDateTimeTz(iso: string, tz: string): string {
  const d = parseUtc(iso);
  if (Number.isNaN(d.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: resolveTz(tz),
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(d);
  } catch {
    return iso;
  }
}

export interface ShareState {
  graphText: string;
  config: Config;
  compare: CompareState;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function isConfig(v: unknown): v is Config {
  if (typeof v !== "object" || v === null) return false;
  const c = v as Record<string, unknown>;
  return (
    typeof c.start === "string" &&
    typeof c.end === "string" &&
    typeof c.interval === "string" &&
    typeof c.initial_capital === "number"
  );
}

function isCompareState(v: unknown): v is CompareState {
  if (typeof v !== "object" || v === null) return false;
  const c = v as Record<string, unknown>;
  return (
    typeof c.enabled === "boolean" &&
    (c.mode === "previous" || c.mode === "yoy" || c.mode === "custom") &&
    typeof c.start === "string" &&
    typeof c.end === "string"
  );
}

function isShareState(v: unknown): v is ShareState {
  if (typeof v !== "object" || v === null) return false;
  const s = v as Record<string, unknown>;
  return typeof s.graphText === "string" && isConfig(s.config) && isCompareState(s.compare);
}

/** Encode shareable backtest state as a URL-safe (base64url) string. Unicode-safe. */
export function encodeShareState(state: ShareState): string {
  const json = JSON.stringify(state);
  const bytes = new TextEncoder().encode(json);
  return bytesToBase64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decode a base64url share string back into state. Never throws; returns null when malformed. */
export function decodeShareState(encoded: string): ShareState | null {
  try {
    if (!encoded) return null;
    let b64 = encoded.replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4 !== 0) b64 += "=";
    const json = new TextDecoder().decode(base64ToBytes(b64));
    const parsed = JSON.parse(json) as unknown;
    return isShareState(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
