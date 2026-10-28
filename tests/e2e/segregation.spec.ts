import { expect, test } from "@playwright/test";
import { apiCall, freeFindings, login } from "./helpers";

test.describe.configure({ mode: "serial" });

test("case approval enforces segregation of duties", async ({ browser }) => {
  const [officerFinding, managerFinding] = await freeFindings(2);

  // 1. Officer opens a case from the finding detail screen.
  const officer = await browser.newPage();
  await login(officer, "compliance.officer");
  await officer.goto(`/risks/${officerFinding}`);
  await officer.getByLabel("Rationale").fill("E2E: verified missing filing; recommend approved reminder");
  await officer.getByRole("button", { name: "Open case" }).click();
  await officer.waitForURL(/\/cases\/[0-9a-f-]{36}$/);
  const caseId = officer.url().split("/").pop()!;
  await expect(officer.getByText("Pending manager approval")).toBeVisible();

  // Officer cannot approve: the control is hidden and the API refuses.
  await expect(officer.getByRole("button", { name: "Approve case" })).toHaveCount(0);
  const denied = await apiCall<{ error: { message: string } }>(
    "compliance.officer",
    "POST",
    `/cases/${caseId}/approve`,
    { note: "self approve" },
  );
  expect(denied.status).toBe(403);
  await officer.close();

  // 2. A manager cannot approve a case they created themselves (API 403 surfaced in the UI).
  const created = await apiCall<{ id: string }>("compliance.manager", "POST", "/cases", {
    finding_id: managerFinding,
    rationale: "E2E: manager-created case for segregation test",
  });
  expect(created.status).toBe(201);
  try {
    const manager = await browser.newPage();
    await login(manager, "compliance.manager");
    await manager.goto(`/cases/${created.data.id}`);
    await expect(manager.getByText("You created this case")).toBeVisible();
    await manager.getByLabel("Decision note").fill("Attempting to approve my own case");
    await manager.getByRole("button", { name: "Approve case" }).click();
    await expect(manager.locator('[data-state="forbidden"]')).toContainText(
      "Segregation of duties: the case creator cannot approve it",
    );
    await expect(manager.getByTestId("trace-id")).not.toBeEmpty();

    // 3. The manager approves the officer's case.
    await manager.goto(`/cases/${caseId}`);
    await manager.getByLabel("Decision note").fill("E2E: approved for reminder");
    await manager.getByRole("button", { name: "Approve case" }).click();
    await expect(manager.locator('[data-state="approved"]').first()).toContainText("Approved by compliance.manager");
    await expect(manager.getByRole("button", { name: "Approve case" })).toHaveCount(0);

    // 4. Contact through an approved template is recorded but never sent from the demo environment.
    const approved = await apiCall<{ outward_permitted: boolean; outward_blockers: string[] }>(
      "compliance.manager",
      "GET",
      `/cases/${caseId}`,
    );
    if (approved.data.outward_permitted && approved.data.outward_blockers.length === 0) {
      await manager.getByLabel("Action type").selectOption("contact_taxpayer");
      await manager.getByLabel("Approved communication template").selectOption("PAYE_RETURN_REMINDER_V1");
      await manager.getByRole("textbox", { name: "Detail", exact: true }).fill("E2E reminder using approved template");
      await manager.getByRole("button", { name: "Record action" }).click();
      await expect(manager.locator(".delivery-status").first()).toHaveText("not_sent_demo_environment");
    }

    // 5. Signed evidence packet export requires a declared purpose.
    await manager.getByLabel(/Declared purpose/).selectOption("desk_review");
    await manager.getByRole("button", { name: "Export evidence packet" }).click();
    await expect(manager.getByTestId("packet-sha")).toHaveText(/^[0-9a-f]{64}$/);
    await manager.close();
  } finally {
    // Clean-up: a second manager rejects the manager-created case so its finding can be reused next run.
    const rejected = await apiCall("compliance.manager2", "POST", `/cases/${created.data.id}/reject`, {
      note: "E2E clean-up",
    });
    expect(rejected.status).toBe(200);
  }
});
