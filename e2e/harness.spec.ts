import { expect, test, type APIRequestContext } from "@playwright/test";

function todo(claimId: string, status: string) {
  return { text: `Work ${claimId}`, status, claim_id: claimId };
}

async function release(request: APIRequestContext, claimId: string) {
  await request.post(`/api/claims/${claimId}/start`);
  await request.post(`/api/claims/${claimId}/release`, {
    data: { reason: "The model timed out.", counts_as_attempt: true },
  });
}

test("the queue shows the run's to-do list as it is ticked off", async ({
  page,
  request,
}) => {
  const run = (await (
    await request.post("/api/runs", { data: { claim_limit: 2 } })
  ).json()) as { run_id: number };
  const todos = `/api/runs/${String(run.run_id)}/todos`;
  await request.put(todos, {
    data: [todo("CLM-1020", "in_progress"), todo("CLM-1021", "todo")],
  });

  await page.goto("/");
  const panel = page.getByRole("region", { name: "Current run" });
  await expect(panel.getByRole("listitem")).toHaveCount(2);
  await expect(panel.getByRole("listitem").first()).toContainText(
    "In progressWork CLM-1020",
  );

  await request.put(todos, {
    data: [todo("CLM-1020", "done"), todo("CLM-1021", "in_progress")],
  });
  await expect(panel.getByRole("listitem").first()).toContainText(
    "DoneWork CLM-1020",
  );

  await request.post(`/api/runs/${String(run.run_id)}/finish`, {
    data: { summary: "Two claims worked." },
  });
  await expect(page.getByRole("heading", { name: "Last run" })).toBeVisible();
  await expect(page.getByText("Two claims worked.")).toBeVisible();
});

test("a claim shows the sections the agent read", async ({ page, request }) => {
  await request.post("/api/claims/CLM-1010/start");
  for (const text of [
    "Claims manual 9. Repeat claims",
    "Policy wording 3. Trip Delay",
  ]) {
    await request.post("/api/claims/CLM-1010/steps", {
      data: { kind: "read", text },
    });
  }
  await page.goto("/#/claims/CLM-1010");
  const panel = page
    .getByRole("heading", { name: "What the agent read" })
    .locator("..");
  await expect(panel.getByRole("listitem")).toHaveText([
    "Claims manual 9. Repeat claims",
    "Policy wording 3. Trip Delay",
  ]);
});

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  await release(request, "CLM-1011");
  await release(request, "CLM-1011");
  await page.goto("/");
  await expect(page.getByRole("row", { name: /CLM-1011/ })).toContainText(
    "Left for a handler",
  );
  await page.getByRole("link", { name: "CLM-1011" }).click();
  await expect(page.getByText("Failed 2 times")).toBeVisible();
  await expect(page.getByText("The model timed out.").first()).toBeVisible();
});
