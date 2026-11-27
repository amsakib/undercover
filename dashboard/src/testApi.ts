import { vi } from "vitest";
import type { Claim, ClaimRow, Policy } from "./api";

export const ROW: ClaimRow = {
  claim_id: "CLM-1001",
  claim_type: "trip_delay",
  summary: "Flight home canceled",
  submitted_on: "2026-06-24",
  amount_claimed: 420,
  status: "waiting",
  attempts: 0,
};

export const CLAIM: Claim = {
  ...ROW,
  policy_id: "POL-2001",
  customer_id: "CUS-3001",
  incident_date: "2026-06-18",
  incident_location: "Rome, Italy",
  story: "My flight home from Rome was canceled.",
  items: [
    { description: "Airport hotel", category: "accommodation", amount: 420 },
  ],
  documents: [
    { name: "Hotel receipt", type: "receipt", content: "Total paid: $420.00." },
  ],
  decision: null,
  payment: null,
};

export const POLICY: Policy = {
  policy_id: "POL-2001",
  plan: "premium",
  add_ons: [],
  purchased_on: "2026-04-22",
  trip: {
    destination: "Rome, Italy",
    departs_on: "2026-06-10",
    returns_on: "2026-06-18",
    trip_cost: 3100,
  },
  travelers: ["Maya Patel"],
};

export type Routes = Record<string, unknown>;

export function mockApi(routes: Routes) {
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${input}`;
    if (!(key in routes))
      return Promise.resolve(new Response("{}", { status: 404 }));
    return Promise.resolve(new Response(JSON.stringify(routes[key])));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
