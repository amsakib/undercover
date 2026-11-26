import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ClaimRow } from "./api";
import { QueuePage } from "./QueuePage";
import { mockApi, ROW } from "./testApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const STATUSES: ClaimRow["status"][] = [
  "waiting",
  "in_progress",
  "awaiting_signoff",
  "decided",
];

function queue(): ClaimRow[] {
  return Array.from({ length: 25 }, (_, i) => ({
    ...ROW,
    claim_id: `CLM-${String(1001 + i)}`,
    status: STATUSES[i % 4] ?? "waiting",
  }));
}

it("lists every claim with its status", async () => {
  mockApi({ "GET /api/claims": queue() });
  render(<QueuePage />);
  expect(await screen.findByText("CLM-1001")).toBeDefined();
  expect(screen.getAllByRole("row")).toHaveLength(26);
  expect(screen.getAllByText("Waiting")).toHaveLength(7);
  expect(screen.getAllByText("In progress")).toHaveLength(6);
  expect(screen.getAllByText("Waiting for sign-off")).toHaveLength(6);
  expect(screen.getAllByText("Decided")).toHaveLength(6);
  expect(screen.getAllByText("$420.00")).toHaveLength(25);
  expect(screen.getByText("CLM-1001").getAttribute("href")).toBe(
    "#/claims/CLM-1001",
  );
  expect(screen.getByText(/25 claims · 7 waiting/)).toBeDefined();
});

it("refreshes the queue", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetchMock = mockApi({ "GET /api/claims": [ROW] });
  render(<QueuePage />);
  await screen.findByText("CLM-1001");
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
});

it("says when the backend is down", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<QueuePage />);
  expect(
    await screen.findByText("The backend is not responding."),
  ).toBeDefined();
});
