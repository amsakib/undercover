export type Status =
  "waiting" | "in_progress" | "awaiting_signoff" | "decided" | "needs_handler";

export interface ClaimRow {
  claim_id: string;
  claim_type: string;
  summary: string;
  submitted_on: string;
  amount_claimed: number;
  status: Status;
  attempts: number;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface ClaimDocument {
  name: string;
  type: string;
  content: string;
}

export interface Decision {
  decision: "approve" | "decline" | "refer";
  payout: number;
  reasons: string;
  policy_section: string;
  decided_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Payment {
  amount: number;
  paid_by: string;
  paid_at: string;
}

export interface Claim extends ClaimRow {
  policy_id: string;
  customer_id: string;
  incident_date: string;
  incident_location: string;
  story: string;
  items: Item[];
  documents: ClaimDocument[];
  decision: Decision | null;
  payment: Payment | null;
}

export interface Policy {
  policy_id: string;
  plan: string;
  add_ons: string[];
  purchased_on: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
}

export interface Step {
  step_id: number;
  kind: "tool_call" | "tool_result" | "message" | "read" | "error";
  text: string;
  at: string;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
}

export interface Todo {
  text: string;
  status: "todo" | "in_progress" | "done" | "handler";
  claim_id: string | null;
}

export interface Run {
  run_id: number;
  claim_limit: number;
  status: "running" | "finished";
  todos: Todo[];
  summary: string;
  started_at: string;
  finished_at: string | null;
}

export type InstructionsName = "queue" | "claim";

export const POLL_MS = 2000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok)
    throw new Error(`${path} returned ${String(response.status)}`);
  return (await response.json()) as T;
}

export const api = {
  latestRun: () => request<Run | null>("/api/runs/latest"),
  claims: () => request<ClaimRow[]>("/api/claims"),
  claim: (id: string) => request<Claim>(`/api/claims/${id}`),
  policy: (id: string) => request<Policy>(`/api/policies/${id}`),
  steps: (id: string) => request<Step[]>(`/api/claims/${id}/steps`),
  handlers: () => request<Handler[]>("/api/handlers"),
  instructions: (name: InstructionsName) =>
    request<{ text: string }>(`/api/instructions/${name}`),
  signOff: (id: string, handlerId: string) =>
    request<Claim>(`/api/claims/${id}/sign-off`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ handler_id: handlerId }),
    }),
};
