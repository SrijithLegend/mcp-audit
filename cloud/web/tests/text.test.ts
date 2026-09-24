import { describe, expect, it } from "vitest";

import { ago, callLine, clip, csvCell, hasHidden, money, pct, rate, visible } from "@/lib/text";

/**
 * How this app renders attacker-controlled text. These are the security tests of the
 * frontend: everything a server wrote reaches the DOM through these functions.
 */
describe("visible()", () => {
  const hidden: Array<[string, string, string]> = [
    ["zero-width space", "read​file", "read<U+200B>file"],
    ["zero-width non-joiner", "a‌b", "a<U+200C>b"],
    ["zero-width joiner", "a‍b", "a<U+200D>b"],
    ["left-to-right mark", "a‎b", "a<U+200E>b"],
    ["right-to-left override", "a‮b", "a<U+202E>b"],
    ["pop directional formatting", "a‬b", "a<U+202C>b"],
    ["word joiner", "a⁠b", "a<U+2060>b"],
    ["first strong isolate", "a⁨b", "a<U+2068>b"],
    ["byte order mark", "a﻿b", "a<U+FEFF>b"],
    ["tag latin small letter a", "a\u{e0061}b", "a<U+E0061>b"],
  ];

  it.each(hidden)("shows %s", (_name, input, expected) => {
    expect(visible(input)).toBe(expected);
  });

  it("leaves ordinary text alone, including newlines and tabs", () => {
    expect(visible("read_file\n\tpath=/etc/passwd")).toBe("read_file\n\tpath=/etc/passwd");
    expect(visible("naïve — ok ✓")).toBe("naïve — ok ✓");
  });

  it("shows other control characters too", () => {
    expect(visible("a\u0007b")).toBe("a<U+0007>b");
  });

  it("never returns markup", () => {
    // React escapes anyway; this asserts we do not helpfully "fix" anything into HTML.
    expect(visible("<script>alert(1)</script>")).toBe("<script>alert(1)</script>");
  });
});

describe("hasHidden()", () => {
  it("is true only when something is actually invisible", () => {
    expect(hasHidden("plain text")).toBe(false);
    expect(hasHidden("sneaky​text")).toBe(true);
    expect(hasHidden("bidi ‮ attack")).toBe(true);
  });
});

describe("callLine()", () => {
  it("renders a call with its arguments as one line", () => {
    expect(callLine({ name: "read_file", arguments: { path: "/etc/passwd" } })).toBe(
      'read_file(path="/etc/passwd")',
    );
  });

  it("makes hidden characters in a tool name visible", () => {
    expect(callLine({ name: "read​file", arguments: {} })).toBe("read<U+200B>file()");
  });

  it("handles nested arguments without breaking", () => {
    expect(callLine({ name: "t", arguments: { a: { b: [1, 2] } } })).toBe('t(a={"b":[1,2]})');
  });
});

describe("number and rate formatting", () => {
  it("shows rates as hits over trials", () => {
    expect(rate(5, 5)).toBe("5/5");
    expect(rate(0, 10)).toBe("0/10");
    expect(rate(1, 0)).toBe("—");
  });

  it("rounds percentages and never divides by zero", () => {
    expect(pct(5, 5)).toBe("100%");
    expect(pct(1, 3)).toBe("33%");
    expect(pct(0, 0)).toBe("—");
  });

  it("shows small costs with enough precision to be useful", () => {
    expect(money(0)).toBe("$0");
    expect(money(0.0034)).toBe("$0.0034");
    expect(money(1.5)).toBe("$1.50");
  });
});

describe("clip()", () => {
  it("says when it truncated", () => {
    expect(clip("short", 10)).toEqual({ text: "short", clipped: false });
    expect(clip("0123456789", 5)).toEqual({ text: "01234", clipped: true });
  });
});

describe("csvCell()", () => {
  it("defuses formula injection", () => {
    // Excel executes a cell starting with = + - @ (docs/SECURITY.md §8).
    expect(csvCell("=1+1")).toBe("\"'=1+1\"");
    expect(csvCell("+cmd")).toBe("\"'+cmd\"");
    expect(csvCell("-2")).toBe("\"'-2\"");
    expect(csvCell("@SUM(A1)")).toBe("\"'@SUM(A1)\"");
    expect(csvCell("read_file")).toBe('"read_file"');
  });

  it("escapes quotes", () => {
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
  });
});

describe("ago()", () => {
  it("degrades gracefully on nonsense", () => {
    expect(ago(null)).toBe("—");
    expect(ago("not a date")).toBe("—");
  });

  it("reads in the units a human would use", () => {
    const now = Date.now();
    expect(ago(new Date(now - 5_000).toISOString())).toMatch(/s ago$/);
    expect(ago(new Date(now - 300_000).toISOString())).toMatch(/m ago$/);
    expect(ago(new Date(now - 7_200_000).toISOString())).toMatch(/h ago$/);
    expect(ago(new Date(now - 4 * 86_400_000).toISOString())).toMatch(/d ago$/);
  });
});
