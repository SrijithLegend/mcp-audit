"use client";

import { useState } from "react";

import { useCreateToken, useMe, useRevokeToken, useTokens } from "@/lib/api";
import { ago } from "@/lib/text";
import {
  Alert,
  Button,
  Card,
  Cell,
  Empty,
  Field,
  Row,
  Spinner,
  Table,
  inputClass,
} from "@/components/ui";

export default function Tokens() {
  const me = useMe();
  const tokens = useTokens();
  const create = useCreateToken();
  const revoke = useRevokeToken();
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);

  const live = tokens.data?.items.filter((token) => !token.revoked_at) ?? [];

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">API tokens</h1>
        <p className="dim text-sm">
          For CI and for <code>mcp-audit login</code>. A token can create and read scans in this
          organisation; it cannot touch billing, seats or other tokens.
        </p>
      </header>

      {fresh && (
        <Alert kind="warn">
          <p className="font-semibold">Copy this now — it is not shown again.</p>
          <pre className="hostile surface mt-2 rounded p-2 text-xs">{fresh}</pre>
          <p className="dim mt-1 text-xs">
            We store only a sha256 of it, so we genuinely cannot show it to you later.
          </p>
        </Alert>
      )}

      <Card title="Create a token">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <Field label="Name" hint="What will use it, so you know what you are revoking later." htmlFor="token-name">
              <input
                id="token-name"
                className={inputClass}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="github-actions"
              />
            </Field>
          </div>
          <Button
            variant="primary"
            disabled={!name || create.isPending}
            onClick={() =>
              create.mutate(
                { name },
                {
                  onSuccess: (token) => {
                    setFresh(token.token);
                    setName("");
                  },
                },
              )
            }
          >
            Create
          </Button>
          <span className="dim text-xs">
            {live.length} of {me.data?.entitlements.api_tokens ?? 1} on this plan
          </span>
        </div>
        {create.isError && (
          <div className="mt-3">
            <Alert kind="error">{create.error.message}</Alert>
          </div>
        )}
      </Card>

      <Card title="Tokens">
        {tokens.isLoading ? (
          <Spinner />
        ) : (tokens.data?.items.length ?? 0) === 0 ? (
          <Empty>No tokens yet.</Empty>
        ) : (
          <Table head={["name", "prefix", "last used", "created", "state", ""]}>
            {tokens.data?.items.map((token) => (
              <Row key={token.id}>
                <Cell className="font-semibold">{token.name}</Cell>
                <Cell className="dim">{token.prefix}…</Cell>
                <Cell className="dim">{ago(token.last_used_at)}</Cell>
                <Cell className="dim">{ago(token.created_at)}</Cell>
                <Cell>{token.revoked_at ? "revoked" : "active"}</Cell>
                <Cell>
                  {!token.revoked_at && (
                    <Button size="sm" variant="danger" onClick={() => revoke.mutate(token.id)}>
                      Revoke
                    </Button>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        <p className="dim mt-3 text-xs">
          Revocation takes effect immediately — the next request with that token is rejected.
        </p>
      </Card>
    </div>
  );
}
