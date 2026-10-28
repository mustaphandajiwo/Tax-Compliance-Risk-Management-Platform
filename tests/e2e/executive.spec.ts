import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("executive sees dashboard metrics with denominators and cannot open the risk register", async ({ page }) => {
  await login(page, "executive.chairman");
  await expect(page.getByRole("heading", { level: 1, name: "NGSIRS Compliance Overview" })).toBeVisible();
  await expect(page.getByRole("note", { name: "Data notice" })).toContainText("SYNTHETIC DATA");

  const filing = page.locator('[data-metric-key="paye_on_time_filing"]');
  await expect(filing).toBeVisible();
  for (const term of ["Numerator", "Denominator", "Time window", "Completeness"]) {
    await expect(filing.getByText(term, { exact: true })).toBeVisible();
  }
  // Every KPI card exposes its denominator.
  const cards = page.locator("article.ng-metric");
  const n = await cards.count();
  expect(n).toBeGreaterThan(3);
  for (let i = 0; i < n; i++) await expect(cards.nth(i).getByText("Denominator", { exact: true })).toBeVisible();

  await expect(page.getByRole("heading", { name: "Confirmed assessed arrears" }).first()).toBeVisible();
  await expect(page.getByText("never shown as arrears")).toBeVisible();

  // No Risk Register in navigation; direct navigation shows the permission state.
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Risk Register" }),
  ).toHaveCount(0);
  await page.goto("/risks");
  await expect(page.locator('[data-state="forbidden"]')).toContainText("Your role cannot open the Risk Register");
});

test("executive dashboard is usable at phone width without horizontal scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "executive.chairman");
  await expect(page.locator('[data-metric-key="paye_on_time_filing"]')).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
