# cloud/web — the hosted frontend

Next.js (App Router) + TypeScript strict + Tailwind 4 + TanStack Query, AGPL-3.0 with the
rest of `cloud/`.

```bash
cp .env.example .env.local        # NEXT_PUBLIC_DEV_EMAIL is enough for local work
npm install
npm run dev                       # http://localhost:3000
npm run typecheck && npm test     # tsc strict + vitest
npm run build && npm run e2e      # Playwright, API stubbed at the network layer
```

Without Clerk keys the client sends `Authorization: Bearer dev:<email>`, which the API
accepts **only** when it is running with `ENVIRONMENT=local`.

## The rules this app is built around

- **Server text is data.** Tool descriptions and model arguments render through
  `components/ui.tsx → Hostile`, inside a `<pre>`, as text. No markdown, no HTML, and
  invisible characters are shown as `<U+200B>` rather than hidden — a payload written in
  zero-width joiners is something you should be able to see. `tests/invariants.test.ts`
  greps for `dangerouslySetInnerHTML`, markdown renderers, `innerHTML`, `eval` and `any`.
- **zod at the JSON boundary.** `lib/schema.ts` parses every response. A shape change
  fails loudly there instead of rendering as `undefined` three components deep.
- **One fetch.** `lib/api.ts` is the only place that attaches a credential, and it sends
  `credentials: "omit"` — bearer tokens, never cookies, so there is no CSRF surface.
- **Authorisation is the API's job.** This app never decides who may see what; it sends a
  token and renders the answer. Duplicating the rule in middleware would mean two copies,
  and the one that drifts is the one that lets somebody in.
- **CSP with a per-request nonce** from `middleware.ts`, no `unsafe-inline` for scripts.
- **Verdicts are never colour alone**: the word and a symbol carry the meaning.

## shadcn/ui

`components/ui.tsx` is written in the shape shadcn generates — `cn()`, `cva` variants,
plain files — so `npx shadcn@latest add <component>` drops in beside it without a second
styling system. The registry itself is not vendored: eight components did not justify it.
