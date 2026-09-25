"use client";

import { useAuth } from "@clerk/nextjs";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { z } from "zod";

import {
  ApiTokenRow,
  Change,
  CreatedToken,
  Me,
  Member,
  Monitor,
  Plan,
  Problem,
  Report,
  Scan,
  Subscription,
  Target,
  page,
} from "./schema";

/** Small response shapes that only this client needs. */
const Empty = z.object({}).loose();
const UrlOut = z.object({ url: z.string() });
const ShareOut = z.object({ url: z.string(), token: z.string() });

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** An API error the UI can act on: the `type` code is stable, the detail is for people. */
export class ApiError extends Error {
  constructor(
    readonly problem: Problem,
    readonly status: number,
  ) {
    super(problem.detail);
    this.name = "ApiError";
  }

  get code(): string {
    return this.problem.type.split("/").pop() ?? "error";
  }

  get upgradeUrl(): string | undefined {
    return this.problem.upgrade_url;
  }
}

type Options = {
  method?: string;
  body?: unknown;
  token?: string | null;
  idempotencyKey?: string;
  orgId?: string;
};

/**
 * One fetch for the whole app, and every response validated with zod.
 *
 * The API is the only authority on what a caller may see: this client sends a bearer
 * token and reads the answer. It never decides an authorisation question itself.
 */
export async function request<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  options: Options = {},
): Promise<z.infer<S>> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (options.body !== undefined) headers["content-type"] = "application/json";
  if (options.token) headers.authorization = `Bearer ${options.token}`;
  if (options.idempotencyKey) headers["idempotency-key"] = options.idempotencyKey;
  if (options.orgId) headers["x-org-id"] = options.orgId;

  const response = await fetch(`${API}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    // Bearer tokens, never cookies: nothing to forge cross-site.
    credentials: "omit",
    cache: "no-store",
  });

  if (response.status === 204) return schema.parse({});
  const text = await response.text();
  let parsed: unknown = {};
  try {
    parsed = text ? JSON.parse(text) : {};
  } catch {
    throw new ApiError(
      Problem.parse({ detail: "The API returned something that is not JSON.", status: response.status }),
      response.status,
    );
  }
  if (!response.ok) {
    throw new ApiError(Problem.parse(parsed), response.status);
  }
  return schema.parse(parsed);
}

/**
 * The credential for the API.
 *
 * In local development without Clerk keys, `NEXT_PUBLIC_DEV_EMAIL` produces a
 * `dev:<email>` token, which the API accepts **only** when it is running with
 * ENVIRONMENT=local. It refuses to start with that switch on anywhere else.
 *
 * Two implementations picked at module load rather than one with an `if` inside: a
 * conditional hook call is a rules-of-hooks violation even when the condition is a
 * build-time constant.
 */
const CLERK_ENABLED = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

function useClerkToken(): () => Promise<string | null> {
  const { getToken } = useAuth();
  return () => getToken();
}

function useDevToken(): () => Promise<string | null> {
  const devEmail = process.env.NEXT_PUBLIC_DEV_EMAIL;
  return async () => (devEmail ? `dev:${devEmail}` : null);
}

export const useToken: () => () => Promise<string | null> = CLERK_ENABLED
  ? useClerkToken
  : useDevToken;

function useApi() {
  const getToken = useToken();
  return async <S extends z.ZodTypeAny>(path: string, schema: S, options: Options = {}) =>
    request(path, schema, { ...options, token: await getToken() });
}

export function useMe(): UseQueryResult<Me> {
  const api = useApi();
  return useQuery({ queryKey: ["me"], queryFn: () => api("/v1/me", Me) });
}

export function usePlans(): UseQueryResult<Plan[]> {
  return useQuery({
    queryKey: ["plans"],
    queryFn: () => request("/v1/plans", Plan.array()),
    staleTime: 60 * 60 * 1000,
  });
}

export function useScans(params: { verdict?: string; targetId?: string } = {}) {
  const api = useApi();
  const query = new URLSearchParams();
  if (params.verdict) query.set("verdict", params.verdict);
  if (params.targetId) query.set("target_id", params.targetId);
  const suffix = query.size ? `?${query.toString()}` : "";
  return useQuery({
    queryKey: ["scans", params],
    queryFn: () => api(`/v1/scans${suffix}`, page(Scan)),
  });
}

export function useScan(id: string) {
  const api = useApi();
  // No polling: an uploaded report arrives finished, so there is no state to wait for.
  return useQuery({ queryKey: ["scan", id], queryFn: () => api(`/v1/scans/${id}`, Scan) });
}

export function useReport(id: string, ready: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: ["report", id],
    queryFn: () => api(`/v1/scans/${id}/report.json`, Report),
    enabled: ready,
    staleTime: Infinity,
  });
}

/** Upload a report the user's own CLI produced. There is nothing to run here. */
export function useUploadReport(): UseMutationResult<Scan, Error, Record<string, unknown>> {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api("/v1/scans", Scan, {
        method: "POST",
        body,
        // A double-clicked submit button must not store the report twice.
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["scans"] });
      void client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useDeleteScan() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/v1/scans/${id}`, Empty, { method: "DELETE" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["scans"] });
    },
  });
}

export function useShare(id: string) {
  const api = useApi();
  const client = useQueryClient();
  const invalidate = () => void client.invalidateQueries({ queryKey: ["scan", id] });
  return {
    create: useMutation({
      mutationFn: () => api(`/v1/scans/${id}/share`, ShareOut, { method: "POST" }),
      onSuccess: invalidate,
    }),
    revoke: useMutation({
      mutationFn: () => api(`/v1/scans/${id}/share`, Empty, { method: "DELETE" }),
      onSuccess: invalidate,
    }),
  };
}

export function useTargets() {
  const api = useApi();
  return useQuery({ queryKey: ["targets"], queryFn: () => api("/v1/targets", page(Target)) });
}

export function useCreateTarget() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/v1/targets", Target, { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["targets"] }),
  });
}

export function useDeleteTarget() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/v1/targets/${id}`, Empty, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["targets"] }),
  });
}

export function useMonitors() {
  const api = useApi();
  return useQuery({ queryKey: ["monitors"], queryFn: () => api("/v1/monitors", page(Monitor)) });
}

export function useCreateMonitor() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/v1/monitors", Monitor, { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["monitors"] }),
  });
}

export function useMonitorChanges(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["changes", id],
    queryFn: () => api(`/v1/monitors/${id}/changes`, page(Change)),
  });
}

export function useTokens() {
  const api = useApi();
  return useQuery({ queryKey: ["tokens"], queryFn: () => api("/v1/tokens", page(ApiTokenRow)) });
}

export function useCreateToken() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; expires_in_days?: number }) =>
      api("/v1/tokens", CreatedToken, { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["tokens"] }),
  });
}

export function useRevokeToken() {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/v1/tokens/${id}`, Empty, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["tokens"] }),
  });
}

export function useMembers(orgId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ["members", orgId],
    queryFn: () => api(`/v1/orgs/${orgId}/members`, page(Member)),
    enabled: Boolean(orgId),
  });
}

export function useInviteMember(orgId: string | undefined) {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: string }) =>
      api(`/v1/orgs/${orgId}/members`, Member, { method: "POST", body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["members", orgId] }),
  });
}

export function useSubscription() {
  const api = useApi();
  return useQuery({
    queryKey: ["subscription"],
    queryFn: () => api("/v1/billing/subscription", Subscription),
  });
}

export function useCheckout() {
  const api = useApi();
  return useMutation({
    mutationFn: (body: { plan: string; interval: string }) =>
      api("/v1/billing/checkout", UrlOut, { method: "POST", body }),
  });
}

export function usePortal() {
  const api = useApi();
  return useMutation({ mutationFn: () => api("/v1/billing/portal", UrlOut, { method: "POST" }) });
}

export function reportUrl(id: string, format: "json" | "md" | "sarif"): string {
  return `${API}/v1/scans/${id}/report.${format}`;
}
