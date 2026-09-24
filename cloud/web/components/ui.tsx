import { cva, type VariantProps } from "class-variance-authority";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { Verdict } from "@/lib/schema";
import { hasHidden, visible } from "@/lib/text";

/**
 * The small set of primitives this app needs, in the shape shadcn/ui generates (cva
 * variants, a `cn` helper, plain files) so its components drop in beside them without a
 * second styling system.
 */

const buttonStyles = cva(
  "inline-flex items-center justify-center gap-2 rounded border font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
  {
    variants: {
      variant: {
        primary: "bg-[var(--color-accent)] text-white border-transparent hover:opacity-90",
        secondary: "surface hover:border-[var(--color-accent)]",
        ghost: "border-transparent hover:bg-[var(--surface)]",
        danger: "border-[var(--color-confirmed)] text-[var(--color-confirmed)] hover:bg-[var(--surface)]",
      },
      size: { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-1.5 text-sm" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonStyles>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonStyles({ variant, size }), className)} {...props} />;
}

export function ButtonLink({
  href,
  className,
  variant,
  size,
  children,
  external,
}: {
  href: string;
  className?: string;
  children: ReactNode;
  external?: boolean;
} & VariantProps<typeof buttonStyles>) {
  const classes = cn(buttonStyles({ variant, size }), className);
  if (external) {
    return (
      <a href={href} className={classes} rel="noreferrer noopener">
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={classes}>
      {children}
    </Link>
  );
}

export function Card({
  title,
  children,
  action,
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("surface rounded p-4", className)}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {typeof title === "string" ? <h2 className="text-sm font-semibold">{title}</h2> : title}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

const VERDICT_STYLE: Record<Verdict, { label: string; className: string; symbol: string }> = {
  // Never colour alone: the word and the symbol both carry the meaning (a11y).
  CONFIRMED: {
    label: "CONFIRMED",
    symbol: "●",
    className: "text-[var(--color-confirmed)] border-[var(--color-confirmed)]",
  },
  SUSPECTED: {
    label: "SUSPECTED",
    symbol: "◐",
    className: "text-[var(--color-suspected)] border-[var(--color-suspected)]",
  },
  CLEAN: { label: "CLEAN", symbol: "○", className: "text-[var(--color-clean)] border-[var(--color-clean)]" },
  INCONCLUSIVE: {
    label: "INCONCLUSIVE",
    symbol: "◌",
    className: "text-[var(--color-inconclusive)] border-[var(--color-inconclusive)]",
  },
};

export function VerdictBadge({ verdict, big = false }: { verdict: Verdict; big?: boolean }) {
  const style = VERDICT_STYLE[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-semibold",
        big ? "text-base px-3 py-1" : "text-xs",
        style.className,
      )}
    >
      <span aria-hidden="true">{style.symbol}</span>
      {style.label}
    </span>
  );
}

export const VERDICT_HEADLINE: Record<Verdict, string> = {
  CONFIRMED: "This server's prose changed what the model did.",
  SUSPECTED: "Something changed, but not reliably enough to confirm.",
  CLEAN: "No behaviour change we can attribute to the prose.",
  INCONCLUSIVE: "Nothing measurable happened in this run.",
};

/**
 * Server- or model-supplied text. **The only component that should ever render it.**
 *
 * It goes in a `<pre>` as text: no markdown, no HTML, invisible characters made visible,
 * and a warning when there were any (docs/SECURITY.md §8).
 */
export function Hostile({
  children,
  className,
  label,
}: {
  children: string;
  className?: string;
  label?: string;
}) {
  const hidden = hasHidden(children);
  return (
    <div className={cn("space-y-1", className)}>
      {label && <div className="dim text-xs">{label}</div>}
      {hidden && (
        <p className="text-xs text-[var(--color-suspected)]">
          ⚠ Contains invisible characters, shown below as <code>&lt;U+XXXX&gt;</code>. Hidden
          characters are a real injection technique.
        </p>
      )}
      <pre className="hostile surface max-h-80 overflow-auto rounded p-3 text-xs">{visible(children)}</pre>
    </div>
  );
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-semibold">
        {label}
      </label>
      {children}
      {hint && <p className="dim text-xs">{hint}</p>}
    </div>
  );
}

export const inputClass =
  "w-full rounded border bg-transparent px-2.5 py-1.5 text-sm border-[var(--border)] focus:border-[var(--color-accent)]";

export function Alert({
  kind = "info",
  children,
  action,
}: {
  kind?: "info" | "warn" | "error";
  children: ReactNode;
  action?: ReactNode;
}) {
  const border = {
    info: "border-[var(--color-inconclusive)]",
    warn: "border-[var(--color-suspected)]",
    error: "border-[var(--color-confirmed)]",
  }[kind];
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={cn("surface flex items-start justify-between gap-3 rounded border-l-2 p-3 text-sm", border)}
    >
      <div>{children}</div>
      {action}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="dim py-6 text-center text-sm">{children}</p>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <p className="dim py-6 text-center text-sm" role="status">
      {label}…
    </p>
  );
}

export function Meter({ used, limit, label }: { used: number; limit: number; label: string }) {
  const share = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span>{label}</span>
        <span className="dim">
          {used} / {limit}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded bg-[var(--border)]"
        role="progressbar"
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-label={label}
      >
        <div
          className={cn("h-full", share > 90 ? "bg-[var(--color-confirmed)]" : "bg-[var(--color-accent)]")}
          style={{ width: `${share}%` }}
        />
      </div>
    </div>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="dim">
          <tr>
            {head.map((column) => (
              <th key={column} scope="col" className="border-b border-[var(--border)] px-2 py-1.5 font-normal">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <tr className="border-b border-[var(--border)] last:border-0">{children}</tr>;
}

export function Cell({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cn("px-2 py-1.5 align-top", className)}>{children}</td>;
}
