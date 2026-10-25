import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ProfileOut } from "@/lib/api/types";
import { nav, resetNav } from "@/test/nav";
import { browserApi, expectDataTable, renderWithClient } from "@/test/render";

import { ProfilePage } from "./Profile";

const PROFILE: ProfileOut = {
  email: "anita@example.org",
  full_name: "Anita Sharma",
  mobile: "9864012345",
  memberships: [],
  must_change_password: false,
  must_confirm_profile: false,
  profile_confirmed_at: "2026-10-01T00:00:00Z",
  notification_preferences: {
    in_app: { enabled: true },
    email: { enabled: true, digest: "daily", critical_only: false },
    sms: { available: false },
  },
};

const DEVICES = [
  { id: "d1", label: "Firefox on Windows", user_agent: null, current: true, first_seen_at: "2026-10-01T00:00:00Z", last_seen_at: "2026-10-20T05:00:00Z", revoked_at: null },
];

beforeEach(() => {
  resetNav("/profile");
});

describe("My profile on the Settings template (portal-ui-redesign, decision 26)", () => {
  it("shows the four groups as a sub-menu and one group at a time, Details first", async () => {
    browserApi({ "GET /me/profile": PROFILE, "GET /me/devices": DEVICES });
    const { container } = renderWithClient(<ProfilePage />);
    const menu = await screen.findByRole("navigation", { name: "Profile Settings" });
    const links = within(menu).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Details", "/profile"],
      ["Notifications", "/profile?group=notifications"],
      ["Change Password", "/profile?group=password"],
      ["Devices", "/profile?group=devices"],
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("form", { name: "Details" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Change Password" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Devices" })).toBeNull();
    expect(container.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
  });

  it("?group=devices shows the devices only", async () => {
    browserApi({ "GET /me/profile": PROFILE, "GET /me/devices": DEVICES });
    const { container } = renderWithClient(<ProfilePage params={{ group: "devices" }} />);
    expect(await screen.findByText("Firefox on Windows")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Details" })).toBeNull();
    const menu = screen.getByRole("navigation", { name: "Profile Settings" });
    expect(within(menu).getByRole("link", { name: "Devices" })).toHaveAttribute("aria-current", "page");
    expect(container.querySelectorAll("[data-variant='primary']").length).toBeLessThanOrEqual(1);
  });

  it("an unknown group falls back to Details", async () => {
    browserApi({ "GET /me/profile": PROFILE });
    renderWithClient(<ProfilePage params={{ group: "nope" }} />);
    expect(await screen.findByRole("form", { name: "Details" })).toBeInTheDocument();
  });

  it("on phones the select names the groups and moves to the chosen one", async () => {
    browserApi({ "GET /me/profile": PROFILE });
    renderWithClient(<ProfilePage />);
    const select = await screen.findByLabelText("Setting");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Details", "Notifications", "Change Password", "Devices"]);
    await userEvent.selectOptions(select, "password");
    expect(nav.push).toHaveBeenCalledWith("/profile?group=password");
  });
});

describe("lists are DataTables, cards on phones (design portal-ui-polish, decision 15)", () => {
  it("Profile renders a DataTable with a primary cell", async () => {
    browserApi({ "GET /me/profile": PROFILE, "GET /me/devices": DEVICES });
    renderWithClient(<ProfilePage params={{ group: "devices" }} />);
    await screen.findByText("Firefox on Windows");
    expectDataTable(screen.getByRole("table", { name: "Devices" }));
  });
});
