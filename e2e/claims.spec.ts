import { expect, test, type APIRequestContext } from "@playwright/test";

async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: string,
  payout: number,
) {
  await request.post(`/api/claims/${claimId}/start`);
  await request.post(`/api/claims/${claimId}/steps`, {
    data: { kind: "message", text: `Working on ${claimId}.` },
  });
  const response = await request.post(`/api/claims/${claimId}/decision`, {
    data: {
      decision,
      payout,
      reasons: `Reasons for ${claimId}.`,
      policy_section: "Section 5. Baggage and Personal Effects",
    },
  });
  expect(response.ok()).toBe(true);
}

test("the queue lists every claim in order", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
  const rows = page.getByRole("row");
  await expect(rows).toHaveCount(26);
  await expect(rows.nth(1)).toContainText("CLM-1001");
});

test("a decided claim shows the decision, reasons and steps", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1003", "decline", 0);
  await page.goto("/");
  await expect(page.getByRole("row", { name: /CLM-1003/ })).toContainText(
    "Decided",
  );
  await page.getByRole("link", { name: "CLM-1003" }).click();
  await expect(page.getByText("Declined")).toBeVisible();
  await expect(page.getByText("Reasons for CLM-1003.")).toBeVisible();
  await expect(
    page.getByText("Policy wording: Section 5. Baggage and Personal Effects"),
  ).toBeVisible();
  await expect(page.getByText("Working on CLM-1003.")).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
});

test("a payout over the limit is paid only after a handler signs off", async ({
  page,
  request,
}) => {
  await decide(request, "CLM-1004", "approve", 1250);
  const early = await request.post("/api/claims/CLM-1004/payments", {
    data: { amount: 1250 },
  });
  expect(early.status()).toBe(409);

  await page.goto("/#/claims/CLM-1004");
  await expect(page.getByText("Waiting for sign-off")).toBeVisible();
  await expect(page.getByText("Not paid yet")).toBeVisible();
  await page.getByRole("combobox", { name: "Handler" }).selectOption("HND-03");
  await page
    .getByRole("button", { name: "Sign off and pay $1,250.00" })
    .click();
  await expect(page.getByText("Paid $1,250.00 by HND-03")).toBeVisible();
  await expect(page.getByText("Decided", { exact: true })).toBeVisible();
});

test("the agent's instructions are shown read only", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Instructions" }).click();
  await expect(
    page.getByRole("heading", { name: "Agent instructions" }),
  ).toBeVisible();
  await expect(page.getByText(/You are the UnderCover Agent/)).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
