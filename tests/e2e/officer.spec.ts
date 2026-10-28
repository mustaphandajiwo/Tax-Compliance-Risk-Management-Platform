import { expect, test } from "@playwright/test";
import { RISK_LABEL, login } from "./helpers";

test("officer: risk register shows the evasion label, opens a finding and reproduces its score", async ({ page }) => {
  await login(page, "compliance.officer");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Risk Register" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Risk Register" })).toBeVisible();

  const table = page.getByTestId("risk-table");
  await expect(table).toBeVisible();
  await expect(page.getByText(RISK_LABEL).first()).toBeVisible();
  await expect(page.getByTestId("denominator-note")).toContainText("findings match the filters");
  // Confidence is its own column, separate from the priority index.
  await expect(table.getByRole("columnheader", { name: "Confidence" })).toBeVisible();
  await expect(table.getByRole("columnheader", { name: "Priority index" })).toBeVisible();
  // A null score must never render as 0.
  await expect(table.getByText(/Exposure unknown|Data hold – no score|^\d+$/).first()).toBeVisible();

  const first = table.locator("tbody tr").first().getByRole("rowheader").getByRole("link");
  const ref = (await first.textContent())!.trim();
  await first.click();
  await expect(page).toHaveURL(/\/risks\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText(ref);
  await expect(page.getByText(RISK_LABEL).first()).toBeVisible();
  for (const s of [
    "What triggered",
    "Evidence",
    "Alternative explanations and counter-evidence",
    "Exclusions checked",
    "Event log and reviewer decisions",
  ]) {
    await expect(page.getByRole("heading", { name: s, exact: true })).toBeVisible();
  }
  await expect(page.getByText("Relevant law version")).toBeVisible();

  await page.getByRole("button", { name: "Reproduce score" }).click();
  await expect(page.getByText(/Reproduced: yes/)).toBeVisible();
  await expect(page.getByText("Recomputed outcome hash")).toBeVisible();
});
