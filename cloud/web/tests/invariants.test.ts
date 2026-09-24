import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Frontend invariants, greppable (docs/SECURITY.md §8).
 *
 * Attacker-controlled text reaches this app on every page that shows a report. These
 * tests are the reason a future change cannot quietly start rendering it as HTML.
 */

const ROOT = resolve(__dirname, "..");
const SOURCE_DIRS = ["app", "components", "lib"];

function sources(): Array<{ path: string; text: string }> {
  const out: Array<{ path: string; text: string }> = [];
  const walk = (directory: string) => {
    for (const entry of readdirSync(directory)) {
      const full = join(directory, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (/\.tsx?$/.test(entry)) {
        out.push({ path: full.slice(ROOT.length + 1), text: readFileSync(full, "utf8") });
      }
    }
  };
  for (const directory of SOURCE_DIRS) walk(join(ROOT, directory));
  return out;
}

describe("rendering hostile text", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    // The attribute form, not the word: this file's own docstrings name it, and so do
    // the comments that explain why we do not use it.
    const offenders = sources().filter((file) => /dangerouslySetInnerHTML\s*=/.test(file.text));
    expect(offenders.map((f) => f.path)).toEqual([]);
  });

  it("never pulls in a markdown renderer", () => {
    // A server's tool description is not markdown, and rendering it as markdown would
    // hand it links, images and HTML passthrough.
    // Matched on the import specifier, so a local function called `marked` is not a hit.
    const renderers = /from ["'](react-markdown|marked|markdown-it|remark-html|showdown|dompurify)/;
    const offenders = sources().filter((file) => renderers.test(file.text));
    expect(offenders.map((f) => f.path)).toEqual([]);
  });

  it("never writes to innerHTML or document.write", () => {
    const offenders = sources().filter((file) => /\.innerHTML\s*=|document\.write\(/.test(file.text));
    expect(offenders.map((f) => f.path)).toEqual([]);
  });

  it("never uses eval or new Function", () => {
    const offenders = sources().filter((file) => /\beval\(|new Function\(/.test(file.text));
    expect(offenders.map((f) => f.path)).toEqual([]);
  });
});

describe("typing discipline", () => {
  it("uses `any` nowhere outside a comment", () => {
    // zod is how JSON becomes typed; `any` would defeat the point of having schemas.
    const offenders = sources().filter((file) =>
      file.text
        .split("\n")
        .some(
          (line) =>
            /(:|<|\bas\s)\s*any\b/.test(line) &&
            !line.trimStart().startsWith("//") &&
            !line.trimStart().startsWith("*"),
        ),
    );
    expect(offenders.map((f) => f.path)).toEqual([]);
  });
});

describe("the API client", () => {
  it("is the only place that calls fetch", () => {
    // One place that attaches credentials and validates responses. A stray fetch is a
    // request with no schema and possibly no token.
    const offenders = sources().filter(
      (file) =>
        /\bfetch\(/.test(file.text) &&
        !["lib/api.ts", "app/share/[token]/page.tsx"].includes(file.path.replace(/\\/g, "/")),
    );
    expect(offenders.map((f) => f.path)).toEqual([]);
  });

  it("never sends cookies", () => {
    const client = readFileSync(join(ROOT, "lib/api.ts"), "utf8");
    expect(client).toContain('credentials: "omit"');
    expect(client).not.toContain('credentials: "include"');
  });
});

describe("the CSP", () => {
  const middleware = readFileSync(join(ROOT, "middleware.ts"), "utf8");

  it("has no unsafe-inline or unsafe-eval for scripts", () => {
    const scriptSrc = middleware.match(/script-src[^`]*?\$\{CLERK\}/)?.[0] ?? "";
    expect(scriptSrc).not.toContain("unsafe-inline");
    expect(scriptSrc).not.toContain("unsafe-eval");
    expect(scriptSrc).toContain("nonce-");
  });

  it("blocks framing, plugins and stray form posts", () => {
    expect(middleware).toContain("frame-ancestors 'none'");
    expect(middleware).toContain("object-src 'none'");
    expect(middleware).toContain("base-uri 'none'");
    expect(middleware).toContain("form-action 'self'");
  });

  it("uses a fresh nonce per request", () => {
    expect(middleware).toContain("crypto.randomUUID()");
  });
});
