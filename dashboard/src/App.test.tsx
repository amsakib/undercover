import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { CLAIM, mockApi, POLICY, ROW } from "./testApi";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

it("switches between the queue and a claim by the URL", async () => {
  mockApi({
    "GET /api/claims": [ROW],
    "GET /api/runs/latest": null,
    "GET /api/claims/CLM-1001": CLAIM,
    "GET /api/policies/POL-2001": POLICY,
    "GET /api/claims/CLM-1001/steps": [],
  });
  render(<App />);
  expect(await screen.findByText("Claims queue")).toBeDefined();
  act(() => {
    window.location.hash = "#/claims/CLM-1001";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(await screen.findByText("Back to the queue")).toBeDefined();
});
