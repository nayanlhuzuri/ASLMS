import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";
const list = (process.env.SWEEP_WIDTHS ?? "375,768,1280").split(",").map(Number);
const names: Record<number, string> = { 375: "phone", 768: "tablet", 1280: "laptop" };
const heights: Record<number, number> = { 375: 812, 768: 1024, 1280: 800 };
export const WIDTHS = { phone: { width: 375, height: 812 }, tablet: { width: 768, height: 1024 }, laptop: { width: 1280, height: 800 } };
export default defineConfig({
  testDir: ".", testMatch: ["uicheck.spec.ts"], outputDir: join(tmpdir(), "uicheck-artifacts"),
  globalSetup: "./global-setup.ts", globalTeardown: "./global-teardown.ts", fullyParallel: true,
  workers: Number(process.env.UICHECK_WORKERS ?? 3), retries: 0, timeout: 120_000, reporter: [["line"]],
  use: { baseURL: process.env.UICHECK_BASE_URL ?? "http://web:3000", browserName: "chromium", reducedMotion: "reduce", locale: "en-IN", timezoneId: "Asia/Kolkata", launchOptions: { args: ["--disable-dev-shm-usage"] } },
  projects: list.map((w) => ({ name: names[w] ?? `w${w}`, use: { viewport: { width: w, height: heights[w] ?? 900 } } })),
});
