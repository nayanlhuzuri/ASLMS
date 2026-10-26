import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { MembershipOut, UserChoice } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, json, labels, renderWithClient } from "@/test/render";

import { UserPicker } from "./UserPicker";

function membership(id: string, code: string, role: MembershipOut["role"], extra: Partial<MembershipOut> = {}): MembershipOut {
  return {
    id,
    office: { code, name: code, kind: "department" },
    department_code: code,
    designation: "Secretary",
    role,
    is_primary: false,
    is_active: true,
    ...extra,
  };
}

function person(id: string, name: string, email: string, memberships: MembershipOut[], extra: Partial<UserChoice> = {}): UserChoice {
  return {
    id,
    email,
    full_name: name,
    is_active: true,
    office: memberships.length ? { id: "o", code: memberships[0]!.office.code, name: "x", kind: "department", path: "GOA/x", is_active: true } : null,
    memberships,
    ...extra,
  };
}

const RAVI = person("u-1", "Ravi Das", "ravi@example.org", [
  membership("m-2", "HEALTH", "dept_officer"),
  membership("m-1", "EDU", "dept_head", { is_primary: true }),
  membership("m-3", "AGRI", "dept_head"),
  membership("m-4", "TRANS", "dept_officer"),
]);
const NEW = person("u-2", "Rani Bora", "rani@example.org", []);
const EXITED = person("u-3", "Ramen Kalita", "ramen@example.org", [], {
  office: { id: "o", code: "EDU", name: "Education", kind: "department", path: "GOA/EDU", is_active: true },
});
const OFF = person("u-4", "Rakesh Off", "rakesh@example.org", [membership("m-5", "EDU", "dept_officer", { is_primary: true })], { is_active: false });
const ROOT = person("u-5", "Ranjit Root", "root@example.org", [membership("m-6", "GOA", "super_admin", { is_primary: true })]);
const ALL = [RAVI, NEW, EXITED, OFF, ROOT];

function Harness(props: { includeWithoutOffice?: boolean; blocked?: (u: UserChoice) => string | null }) {
  const [value, setValue] = useState<UserChoice | null>(null);
  return (
    <>
      <UserPicker label="Person" value={value} onChange={setValue} includeWithoutOffice={props.includeWithoutOffice} blocked={props.blocked} />
      <output data-testid="value">{value?.id ?? ""}</output>
    </>
  );
}

function routes(items: UserChoice[] = ALL, total = items.length) {
  return browserApi({
    "GET /reference/labels": labels(),
    "GET /admin/users": () => json(200, items, { "x-total-count": String(total) }),
  });
}

const searches = (api: ReturnType<typeof routes>) => api.calls.filter((c) => c.path.startsWith("/admin/users?"));

beforeEach(() => resetNav("/admin/offices/new"));

describe("the User Picker (design office-head-picker, decision 2)", () => {
  it("asks nothing under 2 characters, then one debounced request with q and limit=20", async () => {
    const api = routes();
    renderWithClient(<Harness />);
    const box = screen.getByRole("combobox", { name: "Person" });
    await userEvent.type(box, "r");
    expect(await screen.findByText("Type at least 2 letters of a name or e-mail")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 400));
    expect(searches(api)).toHaveLength(0);
    await userEvent.type(box, "a");
    await screen.findAllByRole("option");
    expect(searches(api).map((c) => c.path)).toEqual(["/admin/users?q=ra&limit=20"]);
  });

  it("sends include_ended=true only with includeWithoutOffice", async () => {
    const api = routes();
    renderWithClient(<Harness includeWithoutOffice />);
    await userEvent.type(screen.getByRole("combobox", { name: "Person" }), "ra");
    await screen.findAllByRole("option");
    expect(searches(api).map((c) => c.path)).toEqual(["/admin/users?q=ra&limit=20&include_ended=true"]);
  });

  it("shows the offices primary first with Head badges and + n more, or No Office Yet / No Active Office", async () => {
    routes();
    renderWithClient(<Harness />);
    await userEvent.type(screen.getByRole("combobox", { name: "Person" }), "ra");
    const options = await screen.findAllByRole("option");
    const ravi = options[0]!;
    expect(ravi).toHaveTextContent("Ravi Das");
    expect(ravi).toHaveTextContent("ravi@example.org");
    expect(ravi.querySelector("mark")).toHaveTextContent("Ra");
    const offices = [...ravi.querySelectorAll("[data-office]")].map((e) => e.textContent);
    expect(offices[0]).toMatch(/^EDU · Secretary · Dept head/);
    expect(offices).toHaveLength(3);
    expect(within(ravi).getAllByText("Head")).toHaveLength(2);
    expect(ravi).toHaveTextContent("+ 1 more");
    expect(options[1]).toHaveTextContent("No Office Yet");
    expect(options[2]).toHaveTextContent("No Active Office");
  });

  it("greys sign-in off, the Super Administrator and the page's own reasons, and skips them with the keys", async () => {
    routes();
    renderWithClient(<Harness blocked={(u) => (u.id === "u-2" ? "Already the head of this department" : null)} />);
    const box = screen.getByRole("combobox", { name: "Person" });
    await userEvent.type(box, "ra");
    const options = await screen.findAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-disabled", "true");
    expect(options[1]).toHaveTextContent("Already the head of this department");
    expect(options[3]).toHaveTextContent("Sign-in Off — turn it on in Users");
    expect(options[4]).toHaveTextContent("Super Administrator — holds no other office");
    expect(box).toHaveAttribute("aria-activedescendant", options[0]!.id);
    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveAttribute("aria-activedescendant", options[2]!.id);
    await userEvent.keyboard("{ArrowDown}");
    expect(box).toHaveAttribute("aria-activedescendant", options[2]!.id);
    await userEvent.keyboard("{Home}");
    expect(box).toHaveAttribute("aria-activedescendant", options[0]!.id);
    await userEvent.click(options[3]!);
    expect(screen.getByTestId("value")).toHaveTextContent("");
  });

  it("Enter chooses; the box shows the name, the e-mail and the offices line; Escape keeps it; clear empties it", async () => {
    routes();
    renderWithClient(<Harness />);
    const box = screen.getByRole("combobox", { name: "Person" });
    await userEvent.type(box, "ra");
    await screen.findAllByRole("option");
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.getByTestId("value")).toHaveTextContent("u-3");
    expect(box).toHaveValue("Ramen Kalita");
    expect(screen.getByText("ramen@example.org")).toBeInTheDocument();
    expect(screen.getByText("No Active Office")).toBeInTheDocument();
    await userEvent.type(box, "x");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(box).toHaveValue("Ramen Kalita");
    expect(screen.getByTestId("value")).toHaveTextContent("u-3");
    await userEvent.click(screen.getByRole("button", { name: "Clear person" }));
    expect(screen.getByTestId("value")).toHaveTextContent("");
    expect(box).toHaveValue("");
  });

  it("says Showing the first 20 when there are more, and No person matches when nothing does", async () => {
    const many = Array.from({ length: 20 }, (_, i) => person(`p-${i}`, `Rahul ${i}`, `rahul${i}@example.org`, []));
    routes(many, 45);
    const { unmount } = renderWithClient(<Harness />);
    await userEvent.type(screen.getByRole("combobox", { name: "Person" }), "rahul");
    expect(await screen.findByText("Showing the first 20 — type more to narrow")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(20);
    unmount();
    routes([]);
    renderWithClient(<Harness />);
    await userEvent.type(screen.getByRole("combobox", { name: "Person" }), "zz");
    await waitFor(() => expect(screen.getByText("No person matches “zz”")).toBeInTheDocument());
  });
});
