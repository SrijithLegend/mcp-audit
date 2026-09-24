import type { Metadata } from "next";

export const metadata: Metadata = { title: "Refunds" };

export default function Refunds() {
  return (
    <article className="max-w-3xl space-y-4 text-sm">
      <h1 className="text-xl font-semibold">Refund Policy</h1>
      <p className="dim text-xs">Last updated: 2026-09-24.</p>

      <h2 className="text-base font-semibold">14 days on a first subscription</h2>
      <p>
        If the service is not what you expected, email us within 14 days of your first payment for a
        full refund, no explanation needed. There is a free plan and a free CLI precisely so you can
        find that out before paying.
      </p>

      <h2 className="text-base font-semibold">Renewals</h2>
      <p>
        Renewals are refundable pro rata within 7 days if you have used no more than 10% of that
        period&apos;s scan allowance. Cancel any time to stop the next renewal; access continues to
        the end of the period you paid for.
      </p>

      <h2 className="text-base font-semibold">When we refund without being asked</h2>
      <p>
        If our outage or a bug in our engine made your scans unusable, we refund or credit the
        affected period. Scans that fail for a reason on our side never count against your quota in
        the first place.
      </p>

      <h2 className="text-base font-semibold">What is not refundable</h2>
      <p>
        Periods fully consumed, and accounts terminated for abuse. A verdict you disagree with is not
        grounds for a refund by itself — but tell us, because a false positive is a bug and we want
        the report.
      </p>

      <h2 className="text-base font-semibold">How</h2>
      <p>
        Email srijithshaibu@gmail.com from your account address. Refunds are issued by Dodo Payments
        to the original payment method, usually within 5–10 business days.
      </p>
    </article>
  );
}
