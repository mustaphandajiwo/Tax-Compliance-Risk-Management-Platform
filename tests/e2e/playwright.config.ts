import { defineConfig, devices } from "@playwright/test";

const WEB_URL = process.env.WEB_URL ?? "http://localhost:3000";

/**
 * E2E + accessibility tests for the NGSIRS console.
 * Requires the API on :8000 (seeded SYNTHETIC data). The web app is started with `pnpm start`
 * (run `pnpm build` first) unless something is already listening on :3000.
 */
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  // Tests share one database and some create cases; run them one at a time.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  // Artifacts go under apps/web, whose test-results/ and playwright-report/ are already git-ignored.
  reporter: [["list"], ["html", { outputFolder: "../../apps/web/playwright-report", open: "never" }]],
  outputDir: "../../apps/web/test-results",
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1400, height: 900 },
        // Browsers are pre-installed; never download. Override with PW_CHROMIUM_PATH if needed.
        launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
      },
    },
  ],
  webServer: {
    command: "pnpm --filter @ngsirs/web start",
    url: `${WEB_URL}/login`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
