"use client";

import { useState } from "react";

import { useCreateMonitor, useCreateTarget, useDeleteTarget, useMe, useTargets } from "@/lib/api";
import { ago, visible } from "@/lib/text";
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

export default function Targets() {
  const me = useMe();
  const targets = useTargets();
  const create = useCreateTarget();
  const remove = useDeleteTarget();
  const monitor = useCreateMonitor();

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [task, setTask] = useState("");
  const [headers, setHeaders] = useState("");

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Targets</h1>
        <p className="dim text-sm">
          Remote Streamable HTTP endpoints you scan more than once. Stdio servers are not targets:
          reading one means running it, and that happens on your machine.
        </p>
      </header>

      <Card title="Add a remote target">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="name">
            <input
              id="name"
              className={inputClass}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="notes-server (prod)"
            />
          </Field>
          <Field
            label="URL"
            hint="https only, port 443. We refuse anything that resolves to a private or metadata address."
            htmlFor="url"
          >
            <input
              id="url"
              className={inputClass}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com/mcp"
            />
          </Field>
          <Field label="Task (optional)" htmlFor="task">
            <input
              id="task"
              className={inputClass}
              value={task}
              onChange={(event) => setTask(event.target.value)}
              placeholder="Summarise what is in this server"
            />
          </Field>
          <Field
            label="Headers"
            hint="Encrypted, write-only: the API never shows a value again, only the name."
            htmlFor="target-headers"
          >
            <textarea
              id="target-headers"
              rows={2}
              className={inputClass}
              value={headers}
              onChange={(event) => setHeaders(event.target.value)}
              placeholder="Authorization: Bearer ..."
            />
          </Field>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button
            variant="primary"
            disabled={!name || !url || create.isPending}
            onClick={() =>
              create.mutate(
                {
                  name,
                  kind: "remote_http",
                  url,
                  task: task || undefined,
                  headers: parseHeaders(headers),
                },
                {
                  onSuccess: () => {
                    setName("");
                    setUrl("");
                    setTask("");
                    setHeaders("");
                  },
                },
              )
            }
          >
            Add target
          </Button>
          <span className="dim text-xs">
            {targets.data?.items.length ?? 0} of {me.data?.entitlements.targets ?? 1} on this
            plan
          </span>
        </div>
        {create.isError && (
          <div className="mt-3">
            <Alert kind="error">{create.error.message}</Alert>
          </div>
        )}
      </Card>

      <Card title="Your targets">
        {targets.isLoading ? (
          <Spinner />
        ) : (targets.data?.items.length ?? 0) === 0 ? (
          <Empty>No targets yet.</Empty>
        ) : (
          <Table head={["name", "url", "headers", "added", ""]}>
            {targets.data?.items.map((target) => (
              <Row key={target.id}>
                <Cell className="font-semibold">{visible(target.name)}</Cell>
                <Cell className="max-w-sm truncate">{visible(target.url ?? "")}</Cell>
                <Cell className="dim">{target.header_names.join(", ") || "none"}</Cell>
                <Cell className="dim">{ago(target.created_at)}</Cell>
                <Cell>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      disabled={(me.data?.entitlements.monitors ?? 0) === 0 || monitor.isPending}
                      onClick={() => monitor.mutate({ target_id: target.id, enabled: true })}
                    >
                      Monitor
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => remove.mutate(target.id)}>
                      Delete
                    </Button>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        {monitor.isError && (
          <div className="mt-3">
            <Alert kind="error">{monitor.error.message}</Alert>
          </div>
        )}
      </Card>
    </div>
  );
}

function parseHeaders(raw: string): Record<string, string> | undefined {
  const out: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const index = line.indexOf(":");
    if (index > 0) out[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return Object.keys(out).length > 0 ? out : undefined;
}
