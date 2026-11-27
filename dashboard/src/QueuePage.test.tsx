import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ClaimRow, Run } from "./api";
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

const RUN: Run = {
  run_id: 1,
  claim_limit: 5,
  status: "running",
  todos: [
    { text: "Work CLM-1001", status: "done", claim_id: "CLM-1001" },
    { text: "Work CLM-1002", status: "in_progress", claim_id: "CLM-1002" },
    { text: "Work CLM-1003", status: "handler", claim_id: "CLM-1003" },
    { text: "Work CLM-1004", status: "todo", claim_id: "CLM-1004" },
    {
      text: "Check the queue for missed claims",
      status: "todo",
      claim_id: null,
    },
  ],
  summary: "",
  started_at: "2026-11-27T10:00:00+00:00",
  finished_at: null,
};

function runPanel() {
  return within(screen.getByRole("region", { name: "Current run" }));
}

it("shows the current run's to-do list", async () => {
  mockApi({ "GET /api/claims": [ROW], "GET /api/runs/latest": RUN });
  render(<QueuePage />);
  expect(
    await screen.findByRole("heading", { name: "Current run" }),
  ).toBeDefined();
  const items = runPanel().getAllByRole("listitem");
  expect(items.map((li) => li.textContent)).toEqual([
    "DoneWork CLM-1001",
    "In progressWork CLM-1002",
    "Left for a handlerWork CLM-1003",
    "To doWork CLM-1004",
    "To doCheck the queue for missed claims",
  ]);
  expect(runPanel().getByText("Work CLM-1002").getAttribute("href")).toBe(
    "#/claims/CLM-1002",
  );
  expect(runPanel().getByText("Up to 5 claims · Working")).toBeDefined();
  expect(runPanel().getByText("3 of 5 to-dos started or done")).toBeDefined();
});

it("ticks the to-do list off as the run goes", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const routes: Record<string, unknown> = {
    "GET /api/claims": [ROW],
    "GET /api/runs/latest": { ...RUN, todos: [] },
  };
  mockApi(routes);
  render(<QueuePage />);
  expect(
    await screen.findByText("The agent is planning the run."),
  ).toBeDefined();
  routes["GET /api/runs/latest"] = RUN;
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(await screen.findByText("Work CLM-1004")).toBeDefined();
});

it("shows the summary of a finished run", async () => {
  mockApi({
    "GET /api/claims": [ROW],
    "GET /api/runs/latest": {
      ...RUN,
      status: "finished",
      summary: "Four claims decided.\nCLM-1003 is left for a handler.",
    },
  });
  render(<QueuePage />);
  expect(
    await screen.findByRole("heading", { name: "Last run" }),
  ).toBeDefined();
  expect(screen.getByText(/Four claims decided\./)).toBeDefined();
});

it("shows no run panel before the first run", async () => {
  mockApi({ "GET /api/claims": [{ ...ROW, status: "needs_handler" }] });
  render(<QueuePage />);
  expect(await screen.findByText("CLM-1001")).toBeDefined();
  expect(screen.queryByRole("region", { name: "Current run" })).toBeNull();
  expect(screen.getByText("Left for a handler")).toBeDefined();
  expect(screen.getByText(/1 left for a handler/)).toBeDefined();
});

it("says when the run cannot be read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) =>
      Promise.resolve(
        input === "/api/runs/latest"
          ? new Response("{}", { status: 500 })
          : new Response(JSON.stringify([ROW])),
      ),
    ),
  );
  render(<QueuePage />);
  expect(
    await screen.findByText("The backend is not responding."),
  ).toBeDefined();
});
