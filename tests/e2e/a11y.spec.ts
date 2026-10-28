import { expect, test } from "@playwright/test";
import { expectAccessible, login } from "./helpers";

test.describe("accessibility (WCAG 2.x A/AA, serious + critical)", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "compliance.manager");
  });

  test("dashboard", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator('[data-metric-key="paye_on_time_filing"]')).toBeVisible();
    await expectAccessible(page, "Dashboard");
  });

  test("risk register and risk detail", async ({ page }) => {
    await page.goto("/risks");
    await expect(page.getByTestId("risk-table")).toBeVisible();
    await expectAccessible(page, "Risk register");
    await page.getByTestId("risk-table").locator("tbody tr").first().getByRole("rowheader").getByRole("link").click();
    await expect(page.getByRole("heading", { name: "What triggered" })).toBeVisible();
    await expectAccessible(page, "Risk detail");
  });

  test("intervention queue", async ({ page }) => {
    await page.goto("/cases");
    await expect(page.getByRole("heading", { level: 1, name: "Intervention Queue" })).toBeVisible();
    await expect(page.locator('[data-state="loading"]')).toHaveCount(0);
    await expectAccessible(page, "Cases");
  });

  test("data imports", async ({ page }) => {
    await page.goto("/imports");
    await expect(page.getByTestId("batch-table")).toBeVisible();
    await expectAccessible(page, "Imports");
    await page.getByRole("tab", { name: "Quarantine queue" }).click();
    await expect(page.getByTestId("quarantine-table")).toBeVisible();
    await expectAccessible(page, "Quarantine queue");
  });
});
