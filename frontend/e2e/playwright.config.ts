/**
 * The browser check (design portal-ui-polish, decisions 18-22): Chromium at phone 375×812, tablet 768×1024 (below the
 * kit's 820 px breakpoint, so the phone layout) and laptop 1280×800, against the real Compose `web` service
 * (`UICHECK_BASE_URL`, default http://web:3000). Reduced motion, so every screen is drawn in its final state. The run
 * directory (`/out/<YYYYMMDD-HHMM>` in Compose) is made by the global setup.
 */
import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const WIDTHS = { phone: { width: 375, height: 812 }, tablet: { width: 768, height: 1024 }, laptop: { width: 1280, height: 800 } };

export default defineConfig({
  testDir: ".",
  testMatch: "uicheck.spec.ts",
  outputDir: join(tmpdir(), "uicheck-artifacts"),
  globalSetup: "./global-setup.ts",
  globalTeardown: "./global-teardown.ts",
  fullyParallel: true,
  workers: Number(process.env.UICHECK_WORKERS ?? 3),
  retries: 0,
  timeout: 90_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.UICHECK_BASE_URL ?? "http://web:3000",
    browserName: "chromium",
    reducedMotion: "reduce",
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    launchOptions: { args: ["--disable-dev-shm-usage"] },
  },
  projects: Object.entries(WIDTHS).map(([name, viewport]) => ({ name, use: { viewport } })),
});
