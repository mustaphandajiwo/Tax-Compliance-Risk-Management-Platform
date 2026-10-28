import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("data steward sees the quarantine queue", async ({ page }) => {
  await login(page, "data.steward");
  await page.goto("/imports");
  await page.getByRole("tab", { name: "Quarantine queue" }).click();
  const table = page.getByTestId("quarantine-table");
  await expect(table).toBeVisible();
  expect(await table.locator("tbody tr").count()).toBeGreaterThan(0);
  await expect(table.getByRole("button", { name: "Resolve" }).first()).toBeVisible();
});

test("data steward sees an invalid import state for a file with the wrong columns", async ({ page }) => {
  await login(page, "data.steward");
  await page.goto("/imports");
  await page.getByLabel("Feed type").selectOption("ngsirs_payment");
  await page.getByLabel("Source system").selectOption("ngsirs_treasury");
  await page
    .getByLabel("File (CSV)")
    .setInputFiles({ name: "e2e_bad_columns.csv", mimeType: "text/csv", buffer: Buffer.from("foo,bar\n1,2\n") });
  await page.getByLabel("Extracted at (WAT)").fill("2026-10-27T10:00");
  await page.getByRole("button", { name: "Upload and validate" }).click();
  await expect(page.locator('[data-state="invalid_import"]')).toContainText("missing required column");
  await expect(page.getByRole("button", { name: "Commit batch" })).toHaveCount(0);
});
