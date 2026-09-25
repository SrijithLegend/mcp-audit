import { z } from "zod";

/**
 * The JSON boundary. Nothing from the API is trusted as a shape, and nothing inside it
 * is trusted as text: server prose and model arguments reach this app as data and are
 * rendered as data (see `visible()` in lib/text.ts).
 *
 * `any` is allowed nowhere in this app except here, where zod turns it into something
 * typed (CLAUDE.md).
 */

export const verdicts = ["CONFIRMED", "SUSPECTED", "CLEAN", "INCONCLUSIVE"] as const;
export const Verdict = z.enum(verdicts);
export type Verdict = z.infer<typeof Verdict>;

export const ToolCall = z.object({
  name: z.string(),
  arguments: z.record(z.string(), z.unknown()).default({}),
  turn: z.number().int().default(0),
  index: z.number().int().default(0),
});
export type ToolCall = z.infer<typeof ToolCall>;

export const Signal = z.object({
  tool: z.string(),
  kind: z.enum(["called", "called_first", "sensitive", "canary_flow", "optional_populated"]),
  detail: z.string().default(""),
  security_relevant: z.boolean().default(false),
  real_hits: z.number().int(),
  san_hits: z.number().int(),
  n_real: z.number().int(),
  n_san: z.number().int(),
  p_raw: z.number(),
  p_adj: z.number(),
});
export type Signal = z.infer<typeof Signal>;

export const Evidence = z.object({
  call: ToolCall.nullish(),
  trial: z.number().int().nullish(),
  sanitized_summary: z.string().default(""),
});

export const Finding = z.object({
  signal: Signal,
  verdict: Verdict,
  evidence: Evidence.nullish(),
});
export type Finding = z.infer<typeof Finding>;

export const Trace = z.object({
  side: z.enum(["real", "sanitized"]),
  trial: z.number().int(),
  calls: z.array(ToolCall).default([]),
  stop_reason: z.enum(["no_tool_calls", "max_turns", "api_error"]).default("no_tool_calls"),
  input_tokens: z.number().int().default(0),
  output_tokens: z.number().int().default(0),
  cache_read_tokens: z.number().int().default(0),
  api_calls: z.number().int().default(0),
  error: z.string().nullish(),
});
export type Trace = z.infer<typeof Trace>;

export const Report = z.object({
  format: z.string().default("mcp-audit/report@1"),
  engine_version: z.string().default(""),
  created_at: z.string().nullish(),
  target: z.string().default(""),
  inventory_sha256: z.string().default(""),
  server_name: z.string().nullish(),
  model: z.string().default(""),
  task: z.string().default(""),
  trials: z.number().int().default(0),
  stub_mode: z.string().default("canary"),
  escalated: z.boolean().default(false),
  verdict: Verdict.default("CLEAN"),
  tool_verdicts: z.record(z.string(), Verdict).default({}),
  findings: z.array(Finding).default([]),
  traces: z.array(Trace).default([]),
  // prefault, not default: in zod 4 a `.default()` value is handed back as-is, so the
  // inner field defaults would be skipped and `usage.cost_usd` would be undefined.
  usage: z
    .object({
      input_tokens: z.number().int().default(0),
      output_tokens: z.number().int().default(0),
      cache_read_tokens: z.number().int().default(0),
      api_calls: z.number().int().default(0),
      cost_usd: z.number().default(0),
    })
    .prefault({}),
  stripped_diff: z.string().default(""),
  notes: z.array(z.string()).default([]),
});
export type Report = z.infer<typeof Report>;

export const Scan = z.object({
  id: z.string(),
  status: z.enum(["queued", "running", "succeeded", "failed", "canceled"]),
  verdict: Verdict.nullish(),
  trials: z.number().int(),
  model: z.string(),
  task: z.string().nullish(),
  stub_mode: z.string(),
  target_id: z.string().nullish(),
  inventory_id: z.string().nullish(),
  created_via: z.string(),
  cost_usd: z.number().default(0),
  error_code: z.string().nullish(),
  error_detail: z.string().nullish(),
  share_token: z.string().nullish(),
  created_at: z.string(),
  started_at: z.string().nullish(),
  finished_at: z.string().nullish(),
});
export type Scan = z.infer<typeof Scan>;

export const Target = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["inventory", "remote_http"]),
  url: z.string().nullish(),
  task: z.string().nullish(),
  header_names: z.array(z.string()).default([]),
  created_at: z.string(),
});
export type Target = z.infer<typeof Target>;

export const Monitor = z.object({
  id: z.string(),
  target_id: z.string(),
  enabled: z.boolean(),
  paused_reason: z.string().nullish(),
  last_sha256: z.string().nullish(),
  last_checked_at: z.string().nullish(),
  last_status: z.string().nullish(),
  created_at: z.string(),
});
export type Monitor = z.infer<typeof Monitor>;

export const Change = z.object({
  id: z.string(),
  monitor_id: z.string(),
  old_sha256: z.string().nullish(),
  new_sha256: z.string(),
  diff: z.object({
    first_capture: z.boolean().default(false),
    instructions_changed: z.boolean().default(false),
    instructions_before: z.string().default(""),
    instructions_after: z.string().default(""),
    tools_added: z.array(z.string()).default([]),
    tools_removed: z.array(z.string()).default([]),
    prose_changed: z
      .array(z.object({ tool: z.string(), before: z.string(), after: z.string() }))
      .default([]),
    schema_changed: z
      .array(
        z.object({
          tool: z.string(),
          params_before: z.array(z.string()).default([]),
          params_after: z.array(z.string()).default([]),
          required_before: z.array(z.string()).default([]),
          required_after: z.array(z.string()).default([]),
        }),
      )
      .default([]),
    version_before: z.string().nullish(),
    version_after: z.string().nullish(),
  }),
  scan_id: z.string().nullish(),
  created_at: z.string(),
});
export type Change = z.infer<typeof Change>;

export const ApiTokenRow = z.object({
  id: z.string(),
  name: z.string(),
  prefix: z.string(),
  last_used_at: z.string().nullish(),
  expires_at: z.string().nullish(),
  revoked_at: z.string().nullish(),
  created_at: z.string(),
});
export type ApiTokenRow = z.infer<typeof ApiTokenRow>;

export const CreatedToken = ApiTokenRow.extend({ token: z.string() });

export const Me = z.object({
  user_id: z.string().nullish(),
  email: z.string().nullish(),
  orgs: z
    .array(
      z.object({
        id: z.string(),
        name: z.string(),
        slug: z.string(),
        plan: z.string(),
        personal: z.boolean(),
        role: z.string().nullish(),
      }),
    )
    .default([]),
  current_org: z
    .object({
      id: z.string(),
      name: z.string(),
      slug: z.string(),
      plan: z.string(),
      personal: z.boolean(),
      role: z.string().nullish(),
    })
    .nullish(),
  plan: z.string(),
  entitlements: z.object({
    reports_per_month: z.number().int(),
    max_trials: z.number().int(),
    targets: z.number().int(),
    monitors: z.number().int(),
    retention_days: z.number().int(),
    api_tokens: z.number().int(),
    seats: z.number().int(),
    custom_task: z.boolean(),
    features: z.array(z.string()).default([]),
  }),
  usage: z.object({
    period_start: z.string(),
    reports_used: z.number().int(),
    reports_limit: z.number().int(),
    // What the *customer* spent on their own key, read off the reports they uploaded.
    // Informational: it is their bill, and showing it back is the point.
    your_model_cost_usd: z.number(),
  }),
});
export type Me = z.infer<typeof Me>;

export const Plan = z.object({
  plan: z.string(),
  price_monthly_usd: z.number(),
  price_yearly_usd: z.number(),
  reports_per_month: z.number().int(),
  max_trials: z.number().int(),
  targets: z.number().int(),
  monitors: z.number().int(),
  monitor_min_interval_minutes: z.number().int(),
  retention_days: z.number().int(),
  api_tokens: z.number().int(),
  seats: z.number().int(),
  custom_task: z.boolean(),
  features: z.array(z.string()).default([]),
  extra_seat_usd: z.number().nullish(),
});
export type Plan = z.infer<typeof Plan>;

export const Member = z.object({
  user_id: z.string(),
  email: z.string(),
  name: z.string().nullish(),
  role: z.string(),
});
export type Member = z.infer<typeof Member>;

export const Subscription = z.object({
  plan: z.string(),
  status: z.string(),
  provider: z.string(),
  interval: z.string().optional(),
  seats: z.number().int().optional(),
  current_period_end: z.string().nullish(),
  cancel_at_period_end: z.boolean().optional(),
  effective_plan: z.string().optional(),
  manage_url: z.string().optional(),
});

export const SharedReport = z.object({
  verdict: Verdict.nullish(),
  created_at: z.string(),
  report: Report,
});

export function page<T extends z.ZodTypeAny>(item: T) {
  return z.object({ items: z.array(item), next_cursor: z.string().nullish() });
}

/** RFC 9457 problem+json, which is what every API error looks like. */
export const Problem = z.object({
  type: z.string().default(""),
  title: z.string().default("error"),
  status: z.number().int().default(500),
  detail: z.string().default("Something went wrong."),
  upgrade_url: z.string().optional(),
  used: z.number().optional(),
  limit: z.number().optional(),
});
export type Problem = z.infer<typeof Problem>;

/**
 * A finished report from the CLI, validated before it is uploaded.
 *
 * Strict about the fields only a real run produces: every field of the engine's Report has a
 * default, so `{}` would otherwise look like a tidy CLEAN verdict with zero trials.
 */
export const UploadableReport = Report.extend({
  format: z.literal("mcp-audit/report@1"),
  verdict: Verdict,
  model: z.string().min(1, "a report records the model it used"),
  trials: z.number().int().min(2, "one run is noise; a report needs at least 2 trials per arm"),
  inventory_sha256: z.string().min(1, "a report records the inventory it audited"),
});
export type UploadableReport = z.infer<typeof UploadableReport>;

/** The interchange file the CLI writes, validated before it is uploaded. */
export const Inventory = z.object({
  format: z.literal("mcp-audit/inventory@1"),
  instructions: z.string().default(""),
  tools: z
    .array(
      z.object({
        name: z.string(),
        description: z.string().default(""),
        input_schema: z.record(z.string(), z.unknown()).default({}),
      }),
    )
    .min(1, "an inventory with no tools has nothing to audit"),
  server_name: z.string().nullish(),
  server_version: z.string().nullish(),
  protocol_version: z.string().nullish(),
  captured_at: z.string().nullish(),
  source: z.string().default(""),
});
export type Inventory = z.infer<typeof Inventory>;
