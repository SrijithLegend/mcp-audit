# Runbook: leaked secret

Assume exposure means compromise. Rotate first, investigate second — the investigation is
cheaper than the alternative and it keeps just as well.

## Which secret, and what it costs us

| Secret | Blast radius | Rotate |
|---|---|---|
| `ANTHROPIC_API_KEY` | Our money, and anything the key's org can read | Anthropic console → new key → `fly secrets set` |
| `HEADER_ENC_KEY` | Customers' auth headers for monitored targets | See "re-encrypting" below — this one is not a simple swap |
| `BILLING_WEBHOOK_SECRET` | Forged subscription events → free plans | Provider dashboard → new secret → `fly secrets set` |
| `BILLING_API_KEY` | Charges and refunds on our account | Provider dashboard, immediately |
| Clerk secret key | Session forgery | Clerk dashboard → rotate → redeploy web |
| A customer's `mcpa_` token | That org's scans and reports | `DELETE /v1/tokens/{id}`; effective immediately |
| `DATABASE_URL` | Everything | Neon → reset password → `fly secrets set` |

## Do

1. **Rotate.** In the provider, not in our config first — a new value in Fly with the old
   one still valid upstream has achieved nothing.
   ```bash
   fly secrets set ANTHROPIC_API_KEY=sk-ant-... -a mcp-audit-worker   # restarts machines
   ```
2. **Invalidate the old one upstream.** Delete, do not just "stop using".
3. **Look for use.** Anthropic usage by key; `audit_log` for API-token activity;
   `api_tokens.last_used_at` for tokens that should be dormant:
   ```sql
   SELECT id, org_id, name, prefix, last_used_at, revoked_at
   FROM api_tokens WHERE last_used_at > now() - interval '7 days' ORDER BY last_used_at DESC;
   ```
4. **Find how it got out.** `gitleaks detect --no-git` over the working tree, then the
   history; check Sentry for a request body that should have been scrubbed; check logs for
   a key-shaped string (`mcpa_`, `sk-ant-`, `whsec_`) — `logging.py` masks those, so a hit
   means the redactor was bypassed and that is a bug to fix with a test.
5. **Tell whoever is affected.** A leak of `HEADER_ENC_KEY` or the database URL is customer
   data exposure: the privacy policy commits us to notifying affected customers within 72
   hours of confirming it. Write that email.

## Re-encrypting after a `HEADER_ENC_KEY` rotation

Stored header values are AES-GCM with the storage path as AAD, so a new key cannot read old
rows. There is no silent migration:

1. Set the new key and **keep the old one** as `HEADER_ENC_KEY_OLD` for one deploy.
2. Run a one-off re-encrypt: read each `target_secrets` row with the old key, write it back
   with the new one, in a transaction per target.
3. Remove `HEADER_ENC_KEY_OLD`.
4. If the old key is gone or the values are suspect, do not guess: null the rows, pause the
   affected monitors, and ask those customers to re-enter their headers. A monitor that
   silently stops authenticating is worse than one that says it needs attention.

## Do not

- Do not commit the rotated value anywhere to "keep track of it". `.env*` is gitignored and
  gitleaks runs in CI for a reason.
- Do not skip the customer notification because the window looks small. The commitment is
  in the privacy policy; quietly deciding it did not count is how trust goes.
