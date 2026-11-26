import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim, Step } from "./api";
import { ClaimPage } from "./ClaimPage";
import { InstructionsPage } from "./InstructionsPage";
import { CLAIM, mockApi, POLICY } from "./testApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const STEPS: Step[] = [
  {
    step_id: 1,
    kind: "message",
    text: "Reading the claim.",
    at: "2026-11-26T10:00:01+00:00",
  },
  {
    step_id: 2,
    kind: "tool_call",
    text: 'get_claim {"claim_id": "CLM-1001"}',
    at: "2026-11-26T10:00:02+00:00",
  },
  {
    step_id: 3,
    kind: "tool_result",
    text: 'get_claim: {"claim_id": "CLM-1001"}',
    at: "2026-11-26T10:00:03+00:00",
  },
];

const OVER_LIMIT: Claim = {
  ...CLAIM,
  status: "awaiting_signoff",
  decision: {
    decision: "approve",
    payout: 1250,
    reasons: "Covered.",
    policy_section: "Section 5. Baggage and Personal Effects",
    decided_at: "2026-11-26T10:00:00+00:00",
    signed_off_by: null,
    signed_off_at: null,
  },
};

const HANDLERS = [
  {
    handler_id: "HND-01",
    name: "Dana Whitfield",
    role: "Senior Claims Handler",
  },
  { handler_id: "HND-02", name: "Marcus Oyelaran", role: "Claims Handler" },
];

it("shows the agent's steps in order", async () => {
  mockApi({
    "GET /api/claims/CLM-1001": CLAIM,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": STEPS,
  });
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Reading the claim.")).toBeDefined();
  const items = screen.getAllByRole("listitem").map((li) => li.textContent);
  expect(items[0]).toMatch(/\d\d:00:01 Agent/);
  expect(items[1]).toContain("Tool call");
  expect(items[2]).toContain("Result");
  expect(screen.getByText("get_claim")).toBeDefined();
});

it("says when the agent has not started", async () => {
  mockApi({
    "GET /api/claims/CLM-1001": CLAIM,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
  });
  render(<ClaimPage claimId="CLM-1001" />);
  expect(
    await screen.findByText("The agent has not worked on this claim yet."),
  ).toBeDefined();
});

it("polls while the claim is in progress and stops after", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const routes: Record<string, unknown> = {
    "GET /api/claims/CLM-1001": { ...CLAIM, status: "in_progress" },
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
  };
  const fetchMock = mockApi(routes);
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Working")).toBeDefined();
  routes["GET /api/claims/CLM-1001/steps"] = STEPS;
  routes["GET /api/claims/CLM-1001"] = { ...CLAIM, status: "decided" };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(await screen.findByText("Reading the claim.")).toBeDefined();
  expect(screen.queryByText("Working")).toBeNull();
  const calls = fetchMock.mock.calls.length;
  await act(() => vi.advanceTimersByTimeAsync(6000));
  expect(fetchMock.mock.calls).toHaveLength(calls);
});

it("lets a handler sign off a payout over the limit", async () => {
  const fetchMock = mockApi({
    "GET /api/claims/CLM-1001": OVER_LIMIT,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
    "GET /api/handlers": HANDLERS,
    "POST /api/claims/CLM-1001/sign-off": {
      ...OVER_LIMIT,
      status: "decided",
      decision: { ...OVER_LIMIT.decision, signed_off_by: "HND-02" },
      payment: {
        amount: 1250,
        paid_by: "HND-02",
        paid_at: "2026-11-26T10:05:00+00:00",
      },
    },
  });
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Sign-off needed")).toBeDefined();
  await screen.findByRole("option", {
    name: "Marcus Oyelaran, Claims Handler",
  });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "HND-02" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Sign off and pay $1,250.00" }),
  );
  expect(await screen.findByText("Paid $1,250.00 by HND-02")).toBeDefined();
  expect(screen.queryByText("Sign-off needed")).toBeNull();
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[1]?.body).toBe(JSON.stringify({ handler_id: "HND-02" }));
});

it("says when the sign-off fails", async () => {
  mockApi({
    "GET /api/claims/CLM-1001": OVER_LIMIT,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
    "GET /api/handlers": HANDLERS,
  });
  render(<ClaimPage claimId="CLM-1001" />);
  await screen.findByRole("option", {
    name: "Dana Whitfield, Senior Claims Handler",
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Sign off and pay $1,250.00" }),
  );
  expect(
    await screen.findByText(
      "The sign-off did not go through. Please try again.",
    ),
  ).toBeDefined();
});

it("shows the agent's instructions read only", async () => {
  mockApi({
    "GET /api/instructions": { text: "# UnderCover Agent\n\nDecide claims." },
  });
  render(<InstructionsPage />);
  expect(await screen.findByText(/Decide claims\./)).toBeDefined();
  expect(screen.getByText("Read only")).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});
