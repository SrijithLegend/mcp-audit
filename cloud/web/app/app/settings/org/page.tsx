"use client";

import { useState } from "react";

import { useInviteMember, useMe, useMembers } from "@/lib/api";
import {
  Alert,
  Button,
  Card,
  Cell,
  Field,
  Row,
  Spinner,
  Table,
  inputClass,
} from "@/components/ui";

/** Organisation and members. One page, because "who is in it" is the only real setting. */
export default function OrgSettings() {
  const me = useMe();
  const orgId = me.data?.current_org?.id;
  const members = useMembers(orgId);
  const invite = useInviteMember(orgId);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");

  const seats = me.data?.entitlements.seats ?? 1;
  const canInvite = ["owner", "admin"].includes(me.data?.current_org?.role ?? "");

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">Organisation</h1>
        <p className="dim text-sm">
          {me.data?.current_org?.name}
          {me.data?.current_org?.personal ? " (your personal organisation)" : ""} · you are{" "}
          {me.data?.current_org?.role}
        </p>
      </header>

      <Card title="Roles">
        <Table head={["role", "can"]}>
          <Row>
            <Cell className="font-semibold">owner</Cell>
            <Cell>everything, including billing and deleting the organisation</Cell>
          </Row>
          <Row>
            <Cell className="font-semibold">admin</Cell>
            <Cell>tokens, targets, monitors, members</Cell>
          </Row>
          <Row>
            <Cell className="font-semibold">member</Cell>
            <Cell>run scans and read reports</Cell>
          </Row>
        </Table>
      </Card>

      <Card title={`Members (${members.data?.items.length ?? 0} of ${seats} seats)`}>
        {members.isLoading ? (
          <Spinner />
        ) : (
          <Table head={["email", "name", "role"]}>
            {members.data?.items.map((member) => (
              <Row key={member.user_id}>
                <Cell>{member.email}</Cell>
                <Cell className="dim">{member.name ?? "—"}</Cell>
                <Cell>{member.role}</Cell>
              </Row>
            ))}
          </Table>
        )}

        {canInvite && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <Field label="Invite by email" htmlFor="invite-email">
                <input
                  id="invite-email"
                  type="email"
                  className={inputClass}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="colleague@example.com"
                />
              </Field>
            </div>
            <Field label="Role" htmlFor="invite-role">
              <select
                id="invite-role"
                className={inputClass}
                value={role}
                onChange={(event) => setRole(event.target.value)}
              >
                <option value="member">member</option>
                <option value="admin">admin</option>
              </select>
            </Field>
            <Button
              variant="primary"
              disabled={!email || invite.isPending}
              onClick={() => invite.mutate({ email, role }, { onSuccess: () => setEmail("") })}
            >
              Invite
            </Button>
          </div>
        )}
        {invite.isError && (
          <div className="mt-3">
            <Alert kind="error">{invite.error.message}</Alert>
          </div>
        )}
        <p className="dim mt-3 text-xs">
          An invited person joins properly the first time they sign in; the seat is reserved until
          then.
        </p>
      </Card>

      <Card title="Delete your account">
        <p className="dim text-xs">
          <code>DELETE /v1/me</code> removes your account, and any organisation where you are the
          sole owner, within 24 hours. Billing records are kept only where the payment processor or
          tax law requires it. There is no undo, which is why it is an API call and not a button
          here.
        </p>
      </Card>
    </div>
  );
}
