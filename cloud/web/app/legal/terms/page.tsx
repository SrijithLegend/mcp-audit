import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms" };

/** Required by the merchant of record before going live (ROADMAP §5.2). */
export default function Terms() {
  return (
    <article className="max-w-3xl space-y-4 text-sm">
      <h1 className="text-xl font-semibold">Terms of Service</h1>
      <p className="dim text-xs">
        Last updated: 2026-09-24. Operator: Srijith (sole proprietor, India).
      </p>

      <h2 className="text-base font-semibold">1. What the service does</h2>
      <p>
        mcp-audit Cloud runs differential audits of Model Context Protocol servers you nominate and
        returns a report. The engine is the same open-source engine published under the MIT licence,
        and you can run it yourself for free.
      </p>

      <h2 className="text-base font-semibold">2. What the service does not do</h2>
      <p>
        A report measures one model&apos;s behaviour against one captured inventory at one point in
        time. It is not a security certification, not a guarantee that a server is safe, and not
        professional advice. The known limits are published and shown in every report; read them
        before relying on a verdict.
      </p>

      <h2 className="text-base font-semibold">3. Your responsibilities</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          Only submit servers you are authorised to test. Scanning a remote endpoint sends requests
          to it.
        </li>
        <li>
          Do not use the service to attack anyone, to extract free model output, or to circumvent
          plan limits.
        </li>
        <li>Keep your API tokens secret. Activity under your token is your activity.</li>
      </ul>

      <h2 className="text-base font-semibold">4. Plans, quotas and fair use</h2>
      <p>
        Plan limits are enforced in software and published on the pricing page. We may pause hosted
        scanning if our own spending controls trip; the CLI is unaffected and produces the same
        result locally.
      </p>

      <h2 className="text-base font-semibold">5. Payment</h2>
      <p>
        Payments are processed by Dodo Payments as merchant of record. Subscriptions renew until
        cancelled. See the refund policy.
      </p>

      <h2 className="text-base font-semibold">6. Availability</h2>
      <p>
        The service is provided as is, without an uptime commitment. When something is broken we say
        so on the status page.
      </p>

      <h2 className="text-base font-semibold">7. Liability</h2>
      <p>
        To the extent permitted by law, our total liability is limited to the amount you paid in the
        three months before the claim. We are not liable for decisions taken on the basis of a
        report.
      </p>

      <h2 className="text-base font-semibold">8. Termination</h2>
      <p>
        You may cancel at any time; access continues to the end of the period you paid for and then
        reverts to the free plan. We may terminate an account that abuses the service, with notice
        where practical.
      </p>

      <h2 className="text-base font-semibold">9. Changes</h2>
      <p>
        Material changes are announced on the changelog page before they take effect. Continued use
        after that is acceptance.
      </p>

      <h2 className="text-base font-semibold">10. Contact</h2>
      <p>srijithshaibu@gmail.com</p>
    </article>
  );
}
