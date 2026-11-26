import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim } from "./api";
import { ClaimPage } from "./ClaimPage";
import { CLAIM, mockApi, POLICY } from "./testApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function routes(claim: Claim) {
  return {
    "GET /api/claims/CLM-1001": claim,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
    "GET /api/handlers": [],
  };
}

it("shows a claim before the agent decides it", async () => {
  mockApi(routes(CLAIM));
  render(<ClaimPage claimId="CLM-1001" />);
  expect(
    await screen.findByText("My flight home from Rome was canceled."),
  ).toBeDefined();
  expect(
    screen.getByText("The agent has not decided this claim yet."),
  ).toBeDefined();
  expect(screen.getByText("Hotel receipt")).toBeDefined();
  expect(screen.getByText("Total claimed")).toBeDefined();
  expect(await screen.findByText("Premium")).toBeDefined();
  expect(screen.getByText("Maya Patel")).toBeDefined();
});

it("shows the decision, its reasons and the payment", async () => {
  mockApi(
    routes({
      ...CLAIM,
      status: "decided",
      decision: {
        decision: "approve",
        payout: 1250,
        reasons: "The delay is covered.",
        policy_section: "Section 3. Trip Delay",
        decided_at: "2026-11-26T10:00:00+00:00",
        signed_off_by: "HND-01",
        signed_off_at: "2026-11-26T10:05:00+00:00",
      },
      payment: {
        amount: 1250,
        paid_by: "HND-01",
        paid_at: "2026-11-26T10:05:00+00:00",
      },
    }),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Approved")).toBeDefined();
  expect(screen.getByText("$1,250.00")).toBeDefined();
  expect(screen.getByText("The delay is covered.")).toBeDefined();
  expect(
    screen.getByText("Policy wording: Section 3. Trip Delay"),
  ).toBeDefined();
  expect(screen.getByText("Signed off by HND-01")).toBeDefined();
  expect(screen.getByText("Paid $1,250.00 by HND-01")).toBeDefined();
});

it("shows an approved claim that is not paid yet", async () => {
  mockApi(
    routes({
      ...CLAIM,
      status: "decided",
      decision: {
        decision: "approve",
        payout: 420,
        reasons: "Covered.",
        policy_section: "Section 3. Trip Delay",
        decided_at: "2026-11-26T10:00:00+00:00",
        signed_off_by: null,
        signed_off_at: null,
      },
    }),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Not paid yet")).toBeDefined();
});

it("says when there is no such claim", async () => {
  mockApi({});
  render(<ClaimPage claimId="CLM-0000" />);
  expect(await screen.findByText("There is no claim CLM-0000.")).toBeDefined();
});
