/**
 * Rendering attacker-controlled text safely (docs/SECURITY.md §8, invariant 5).
 *
 * Everything an MCP server wrote, and everything a model wrote while being steered by
 * it, passes through here. Two rules:
 *
 * 1. It is never markdown and never HTML. React escapes by default and we never reach
 *    for `dangerouslySetInnerHTML`; that is enforced by a test that greps this app.
 * 2. Invisible and direction-changing characters are *shown*, not hidden. A payload made
 *    of zero-width joiners renders as nothing at all otherwise, which is the whole point
 *    of using them. Showing them is a feature.
 */

const RANGES: Array<[number, number]> = [
  [0x200b, 0x200f], // zero-width space .. right-to-left mark
  [0x202a, 0x202e], // bidi embedding and overrides
  [0x2060, 0x2064], // word joiner, invisible operators
  [0x2066, 0x2069], // bidi isolates
  [0xfeff, 0xfeff], // byte order mark
  [0xe0000, 0xe007f], // tags block: the "hidden instructions" trick
];

function marked(codePoint: number): boolean {
  return RANGES.some(([low, high]) => codePoint >= low && codePoint <= high);
}

/** Replace invisible characters with a visible `<U+XXXX>` marker. */
export function visible(text: string): string {
  let out = "";
  for (const character of text) {
    const code = character.codePointAt(0);
    if (code !== undefined && marked(code)) {
      out += `<U+${code.toString(16).toUpperCase().padStart(4, "0")}>`;
    } else if (code !== undefined && code < 0x20 && character !== "\n" && character !== "\t") {
      out += `<U+${code.toString(16).toUpperCase().padStart(4, "0")}>`;
    } else {
      out += character;
    }
  }
  return out;
}

/** True if the text contains anything a reader would not see. */
export function hasHidden(text: string): boolean {
  for (const character of text) {
    const code = character.codePointAt(0);
    if (code !== undefined && marked(code)) return true;
  }
  return false;
}

/** Truncate for display, keeping the fact that it was truncated. */
export function clip(text: string, limit = 400): { text: string; clipped: boolean } {
  if (text.length <= limit) return { text, clipped: false };
  return { text: text.slice(0, limit), clipped: true };
}

/** A tool call as one readable line. Arguments are data, so they are stringified. */
export function callLine(call: { name: string; arguments: Record<string, unknown> }): string {
  const args = Object.entries(call.arguments)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
  return visible(`${call.name}(${args})`);
}

/** Percentages for the rate columns, without pretending to more precision than n gives. */
export function rate(hits: number, total: number): string {
  if (!total) return "—";
  return `${hits}/${total}`;
}

export function pct(hits: number, total: number): string {
  if (!total) return "—";
  return `${Math.round((hits / total) * 100)}%`;
}

export function money(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

export function shortHash(hash: string): string {
  return hash ? hash.slice(0, 12) : "—";
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

/** CSV export cells: a leading =, +, - or @ is a formula in Excel (§8). */
export function csvCell(value: string): string {
  const escaped = value.replace(/"/g, '""');
  const guarded = /^[=+\-@\t\r]/.test(escaped) ? `'${escaped}` : escaped;
  return `"${guarded}"`;
}
