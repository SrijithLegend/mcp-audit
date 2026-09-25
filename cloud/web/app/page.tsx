import Link from "next/link";

import { ButtonLink, Card } from "@/components/ui";

/**
 * The landing page. One job: make the difference from a static scanner obvious in the
 * first ten seconds, then be honest about the limits before anyone pays.
 */
export default function Landing() {
  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <p className="dim text-xs uppercase tracking-wide">MCP security</p>
        <h1 className="max-w-3xl text-2xl font-semibold sm:text-3xl">
          Static scanners flag suspicious text. mcp-audit proves the text changes what your
          model does.
        </h1>
        <p className="dim max-w-2xl text-sm">
          An MCP server hands your model free text — tool descriptions, parameter
          descriptions, its own <code>instructions</code> — and most hosts paste all of it into
          the system prompt. We capture that surface, strip the prose, and run the same agent
          task against both versions. If the tool calls diverge, the prose did it, and the
          report shows you the call.
        </p>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/docs" variant="primary">
            Get started
          </ButtonLink>
          <ButtonLink href="/pricing">Pricing</ButtonLink>
        </div>
        <pre className="hostile surface rounded p-3 text-xs">
          {`# free, MIT, unlimited -- runs on your own Anthropic key
uvx mcp-audit scan npx -y @some/mcp-server

# and keep the history, diffs and rug-pull alerts
uvx mcp-audit scan npx -y @some/mcp-server --push`}
        </pre>
      </section>

      <Card title="How it works">
        <pre className="hostile overflow-x-auto text-xs leading-relaxed">
          {`   capture (tools/list)
            │
            ├──► real inventory ───────► N trials ──┐
            │    instructions + prose              │   compare features per trial,
            │                                      ├─► Fisher exact, Holm correction
            └──► sanitized inventory ──► N trials ──┘   → CONFIRMED / SUSPECTED / CLEAN

   Same model. Same task. Same stub results. Same tool order. Same turn limit.
   Only the prose differs — so a behaviour change has exactly one possible cause.`}
        </pre>
        <p className="dim mt-3 text-xs">
          Tools are <strong>never executed</strong>. Every call the model makes is answered with
          a dry-run stub, so auditing a filesystem server does not read your <code>~/.ssh</code>.
          Some stubs carry a canary token: if it comes back as an argument to another tool, that
          is data moving between tools — the exfiltration shape, caught without touching real
          data.
        </p>
      </Card>

      <section className="grid gap-4 md:grid-cols-3">
        <Card title="Confirmation, not suspicion">
          <p className="dim text-xs">
            A finding is a measured rate difference across repeated trials with a p-value and the
            divergent call attached. Not a regex that matched the word “ignore”.
          </p>
        </Card>
        <Card title="Rug-pull monitoring">
          <p className="dim text-xs">
            A server that was clean when you installed it can ship new descriptions tomorrow. We
            re-capture on a schedule, hash it, and tell you the moment the text changes — with the
            diff, and the command to re-audit it.
          </p>
        </Card>
        <Card title="CI that fails honestly">
          <p className="dim text-xs">
            SARIF into code scanning, exit code 1 on a confirmed finding, and a cost ceiling that
            is a hard stop rather than a warning.
          </p>
        </Card>
      </section>

      <Card title="What this does not catch">
        <ul className="dim list-disc space-y-1 pl-5 text-xs">
          <li>
            Steering through tool or parameter <strong>names</strong>, or through <code>enum</code>{" "}
            values: they are the call surface, so they have to survive sanitization. A parameter
            called <code>always_read_ssh_key_first</code> gets through us.
          </li>
          <li>Injection through tool results — we never execute a tool, by design.</li>
          <li>A server that changes after the scan. Monitoring narrows that, it does not close it.</li>
          <li>Steering specific to a model we did not run. The model is in every report.</li>
        </ul>
        <p className="dim mt-3 text-xs">
          Published as a benchmark with the scanner comparison, false positives included:{" "}
          <a href="https://github.com/SrijithLegend/mcp-audit/tree/main/bench" rel="noreferrer noopener">
            bench/
          </a>
          .
        </p>
      </Card>

      <Card title="Questions people actually ask">
        <dl className="space-y-3 text-xs">
          <div>
            <dt className="font-semibold">Whose API key runs the scan?</dt>
            <dd className="dim">
              Yours, on your machine or in your CI. We never hold an Anthropic key — not yours, and
              not one of ours for your scans. A test in the repository greps the hosted service to
              prove no code path there can call a model at all. So you are never rationed by our
              budget, and a breach of our database cannot touch your billing account.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Then what am I paying for?</dt>
            <dd className="dim">
              Everything a local CLI cannot do: history you can diff, monitoring that runs while
              you sleep, share links, SARIF in code scanning, and a team that can see all of it.
              The verdict itself is free forever.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Do you run my server?</dt>
            <dd className="dim">
              Not in the cloud, ever. Running a stdio server means executing its code, and that only
              happens on your machine, by your choice. For monitoring we fetch an{" "}
              <code>https://</code> endpoint through an SSRF guard and read its tool list — nothing
              else.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Do you execute the server&apos;s tools?</dt>
            <dd className="dim">No. A grep test in the repository fails the build if any code path could.</dd>
          </div>
          <div>
            <dt className="font-semibold">Is the hosted version more capable than the CLI?</dt>
            <dd className="dim">
              No. It is the same engine and it is literally the CLI&apos;s output. The verdict you
              get for free is the verdict we store.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Will you tell me about a server I depend on?</dt>
            <dd className="dim">
              If we confirm steering in a public server, its maintainer hears first and gets 30
              days. <Link href="/security">Our disclosure policy.</Link>
            </dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
