import { expect, test } from "@playwright/test";
import { expectAccessible, login } from "./helpers";

test("compliance cycle shows all six stages, behaviour segments and every tax type", async ({ page }) => {
  await login(page, "executive.chairman");
  await page.goto("/cycle");
  await expect(page.getByRole("heading", { level: 1, name: "Compliance Cycle" })).toBeVisible();
  for (const key of ["identify", "assess", "analyse", "treat", "implement", "evaluate"]) {
    await expect(page.getByTestId(`cycle-step-${key}`)).toBeVisible();
  }
  await page.getByTestId("cycle-step-evaluate").click();
  await expect(page.getByRole("heading", { level: 2, name: "Monitor and evaluate" })).toBeVisible();
  await expect(page.getByTestId("segments-table")).toContainText("Persistent non-compliance");
  const heads = page.getByTestId("tax-type-table");
  for (const code of ["PAYE", "PITDA", "WHT", "CGT", "SD", "LUC", "BPR", "MVL", "DEVL", "GAM", "MKT"]) {
    await expect(heads.getByText(code, { exact: true })).toBeVisible();
  }
  await expect(heads).not.toContainText(/tenement/i);
  await expectAccessible(page);
});

test("risk register filters by tax type and shows the cycle stage", async ({ page }) => {
  await login(page, "compliance.manager");
  await page.goto("/risks?tax_type=LUC");
  const table = page.getByTestId("risk-table");
  await expect(table).toBeVisible();
  await expect(table.locator("tbody tr").first()).toContainText("LUC");
  await expect(table.getByTestId("cycle-stage").first()).toHaveText("Assess and prioritise");
});
