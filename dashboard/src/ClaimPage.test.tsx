import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim, Step } from "./api";
import { ClaimPage } from "./ClaimPage";
import { CLAIM, mockApi, POLICY } from "./testApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function routes(claim: Claim, steps: Step[] = []) {
  return {
    "GET /api/claims/CLM-1001": claim,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": steps,
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

function step(step_id: number, kind: Step["kind"], text: string): Step {
  return { step_id, kind, text, at: "2026-11-26T10:00:00+00:00" };
}

it("lists the sections the agent read", async () => {
  mockApi(
    routes(CLAIM, [
      step(1, "tool_call", 'get_section {"document": "manual"}'),
      step(2, "read", "Claims manual 9. Repeat claims"),
      step(3, "read", "Policy wording 3. Trip Delay"),
      step(4, "read", "Claims manual 9. Repeat claims"),
    ]),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  const panel = (
    await screen.findByRole("heading", { name: "What the agent read" })
  ).closest("section");
  const items = within(panel ?? document.body).getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual([
    "Claims manual 9. Repeat claims",
    "Policy wording 3. Trip Delay",
  ]);
});

it("says when the agent has read nothing yet", async () => {
  mockApi(routes(CLAIM));
  render(<ClaimPage claimId="CLM-1001" />);
  expect(
    await screen.findByText(
      "The agent has not read the wording or the manual yet.",
    ),
  ).toBeDefined();
});

it("shows a claim left for a handler and its problems", async () => {
  mockApi(
    routes({ ...CLAIM, status: "needs_handler", attempts: 2 }, [
      step(1, "error", "RuntimeError: the model broke"),
    ]),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Left for a handler")).toBeDefined();
  expect(screen.getByText("Failed 2 times")).toBeDefined();
  expect(await screen.findByText("Problem")).toBeDefined();
  const error = screen.getByText("RuntimeError: the model broke");
  expect(error.closest("li")?.className).toContain("step-error");
});

it("shows a claim that failed once", async () => {
  mockApi(routes({ ...CLAIM, attempts: 1 }));
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Failed 1 time")).toBeDefined();
});
