/** A stand-in for `next/navigation` in component tests: the router calls are recorded, the path and query set. */
import { vi } from "vitest";

export const nav = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
  pathname: "/",
  search: new URLSearchParams(),
};

export function resetNav(pathname = "/", search = ""): void {
  nav.push.mockReset();
  nav.replace.mockReset();
  nav.back.mockReset();
  // no overlay mark of an earlier test (useUrlOverlay keeps it in history.state)
  if (typeof window !== "undefined") window.history.replaceState(null, "", window.location.href);
  nav.pathname = pathname;
  nav.search = new URLSearchParams(search);
}

export const navigationModule = {
  useRouter: () => nav,
  usePathname: () => nav.pathname,
  useSearchParams: () => nav.search,
  redirect: vi.fn(),
  notFound: vi.fn(),
};
