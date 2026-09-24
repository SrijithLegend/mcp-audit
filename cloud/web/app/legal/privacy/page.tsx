import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy" };

/** Covers the India DPDP Act and GDPR basics (docs/SECURITY.md §10). */
export default function Privacy() {
  return (
    <article className="max-w-3xl space-y-4 text-sm">
      <h1 className="text-xl font-semibold">Privacy Policy</h1>
      <p className="dim text-xs">
        Last updated: 2026-09-24. Controller: Srijith, India. Contact: srijithshaibu@gmail.com.
      </p>

      <h2 className="text-base font-semibold">What we store</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <strong>Account:</strong> your email, your name if your identity provider supplies one, and
          the organisations you belong to.
        </li>
        <li>
          <strong>Inventories:</strong> the tool names, descriptions and schemas of the servers you
          scan. These can name your internal systems, so we treat them as confidential and never use
          them in benchmarks or marketing without explicit opt-in.
        </li>
        <li>
          <strong>Scan reports and traces:</strong> which tools a model called and with what
          arguments. Arguments are truncated before storage.
        </li>
        <li>
          <strong>Usage and billing:</strong> scan counts, token counts, cost, subscription state.
        </li>
        <li>
          <strong>Auth headers for monitored targets:</strong> encrypted with AES-GCM, held in a
          separate table from the target, never returned by the API after you set them, never logged.
        </li>
      </ul>

      <h2 className="text-base font-semibold">What we never store</h2>
      <p>
        Your LLM API keys — hosted scans run on ours. Card details — the payment processor handles
        those. We run no third-party analytics and no advertising trackers.
      </p>

      <h2 className="text-base font-semibold">How long</h2>
      <p>
        Scans and traces are deleted once they pass your plan&apos;s retention window (7 days on
        Free, 1 year on Pro, 2 years on Team) by a nightly job. Deletion is a delete, not a flag.
      </p>

      <h2 className="text-base font-semibold">Sub-processors</h2>
      <p>
        Anthropic (model inference), Clerk (authentication), Dodo Payments (payments, merchant of
        record), Neon (database), Upstash (queue and cache), Fly.io (API and worker), Vercel (web),
        Sentry (error reports, with request bodies and credentials scrubbed), Resend (email).
      </p>

      <h2 className="text-base font-semibold">Your rights</h2>
      <p>
        Access, correction, export and deletion. <code>DELETE /v1/me</code> deletes your account and,
        if you are the sole owner of an organisation, that organisation&apos;s data within 24 hours —
        except records a payment processor or tax law requires us to keep. Email us and we act within
        30 days.
      </p>

      <h2 className="text-base font-semibold">Transfers and legal basis</h2>
      <p>
        Data is processed in the regions our providers operate, which includes the EU and the US.
        Where GDPR applies, our basis is contract performance for running the service and legitimate
        interest for security and abuse prevention.
      </p>

      <h2 className="text-base font-semibold">Breach</h2>
      <p>
        If customer data is exposed, affected customers are notified by email within 72 hours of us
        confirming it, with what happened and what to do about it.
      </p>
    </article>
  );
}
