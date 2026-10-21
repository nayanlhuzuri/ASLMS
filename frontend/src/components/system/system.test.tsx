import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/shell/PortalShell";
import { resetNav } from "@/test/nav";
import { browserApi, labels, makeMe, renderWithClient } from "@/test/render";
import { routes } from "@/test/systemFixtures";

import { SystemHealth } from "./SystemHealth";

beforeEach(() => {
  resetNav("/system");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the navigation entry", () => {
  it("shows only with admin.service_health, after Data collection", () => {
    const { unmount } = renderWithClient(<Sidebar me={makeMe(["admin.napix_refetch", "reports.state"], "central_operator")} />);
    expect(screen.queryByRole("link", { name: "System health" })).toBeNull();
    unmount();
    browserApi({ "GET /reference/labels": labels() });
    renderWithClient(<Sidebar me={makeMe(["admin.service_health", "admin.data_load", "users.view"], "super_admin")} />);
    const links = within(screen.getByRole("navigation", { name: "Main navigation" }))
      .getAllByRole("link")
      .map((a) => a.textContent);
    const at = links.findIndex((t) => t?.includes("System health"));
    expect(at).toBeGreaterThan(links.findIndex((t) => t?.includes("Data collection")));
    expect(at).toBeLessThan(links.findIndex((t) => t?.includes("Administration")));
  });
});

describe("the System health screen", () => {
  it("renders the 17 cards in four groups with their badge inside a Lead", async () => {
    routes();
    renderWithClient(<SystemHealth params={{}} />);
    expect(await screen.findByRole("heading", { name: "Connection and masters" })).toBeInTheDocument();
    for (const name of ["Cause lists", "Case details", "Searches"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    const cards = screen.getAllByTestId(/^card-/);
    expect(cards).toHaveLength(17);
    for (const c of cards) {
      const lead = c.querySelector("[data-lead='lead']");
      expect(lead).not.toBeNull();
      expect(lead!.textContent).toBe("Working");
    }
    expect(within(screen.getByTestId("card-cnr")).getByRole("button", { name: "Case details by CNR: details" })).toBeInTheDocument();
    expect(screen.getByText("17 of 17 working")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Test now/ })).toBeNull();
  });

  it("shows the overview: ring, the server's sentence and the four figures", async () => {
    routes();
    renderWithClient(<SystemHealth params={{}} />);
    expect(await screen.findByRole("img", { name: "98 % answered" })).toBeInTheDocument();
    expect(await screen.findByText("1 is not working")).toBeInTheDocument();
    expect(screen.getByText("Court calls answered (24 h)")).toBeInTheDocument();
    expect(screen.getByText("Calls left this hour")).toBeInTheDocument();
    expect(screen.getByText("resets about 14:34")).toBeInTheDocument();
    expect(screen.getByText("ASLMS services working")).toBeInTheDocument();
  });

  it("lists the services with words, and Check services again is the only primary button", async () => {
    const api = routes();
    renderWithClient(<SystemHealth params={{}} />);
    const list = (await screen.findByText("Virus scanner")).closest("ul")!;
    expect(list).not.toBeNull();
    expect(within(list).getByText("Not working")).toBeInTheDocument();
    expect(within(list).getAllByText("Working").length).toBeGreaterThan(0);
    await screen.findAllByTestId(/^card-/);
    const primaries = document.querySelectorAll("button[data-variant='primary']");
    expect(primaries).toHaveLength(1);
    expect(primaries[0]).toHaveTextContent("Check services again");
    const before = api.calls.filter((c) => c.path === "/admin/system-health/services").length;
    await userEvent.click(screen.getByRole("button", { name: "Check services again" }));
    await waitFor(() =>
      expect(api.calls.filter((c) => c.path === "/admin/system-health/services").length).toBe(before + 1),
    );
  });

});
