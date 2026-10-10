import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.mock("next/navigation", async () => (await import("./nav")).navigationModule);

afterEach(() => {
  cleanup();
});
