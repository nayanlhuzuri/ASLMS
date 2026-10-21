import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { nav, resetNav } from "@/test/nav";
import { json, renderWithClient } from "@/test/render";
import { consoleOf, detailOf, referenceOf, routes, sendResult, summary, tokenState } from "@/test/systemFixtures";

import { SystemHealth } from "./SystemHealth";

const BASE = "/admin/system-health";
const RAW = { api: "cnr", source: "send", response_id: "r", fetched_at: "2026-10-21T14:33:00+05:30", last_seen_at: "2026-10-21T14:33:00+05:30", token_verified: true, bytes: 40, payload: { cino: "GAHC010118832025" } };

type View = ReturnType<typeof renderWithClient>;

/** A new address: the server page renders the screen again with the new query (inside the same query client). */
function navigate(view: View, ui: ReactElement) {
  view.rerender(<QueryClientProvider client={view.client}>{ui}</QueryClientProvider>);
}

function consoleRoutes(extra: Record<string, unknown> = {}, data = summary()) {
  return routes(data, {
    [`GET ${BASE}/napix/cnr/console`]: consoleOf(),
    [`GET ${BASE}/napix/cnr`]: detailOf("cnr"),
    [`GET ${BASE}/napix/cnr/reference`]: referenceOf(),
    [`GET ${BASE}/napix/token/reference`]: referenceOf("token"),
    ...extra,
  });
}

function stubMotion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("reduce") ? reduced : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => {
  resetNav("/system");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the court cards and the console's address", () => {
  it("a card makes no request other than the list, has no Test now, and opens the console at ?api=cnr&tab=request", async () => {
    const api = consoleRoutes();
    const view = renderWithClient(<SystemHealth params={{}} />);
    const card = await screen.findByTestId("card-cnr");
    expect(within(card).queryByRole("button", { name: /Test now/ })).toBeNull();
    fireEvent.click(card);
    expect(nav.push).toHaveBeenCalledWith("/system?api=cnr&tab=request");
    expect(api.calls.filter((c) => c.method !== "GET")).toHaveLength(0);
    expect(api.calls.some((c) => c.path.includes("/napix/cnr"))).toBe(false);
    navigate(view, <SystemHealth params={{ api: "cnr", tab: "request" }} />);
    expect(await screen.findByRole("dialog", { name: "Case details by CNR" })).toBeInTheDocument();
    // Back: the address loses ?api= and the console closes
    navigate(view, <SystemHealth params={{}} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closing the console goes back after opening it, and drops the tab with the overlay otherwise", async () => {
    consoleRoutes();
    const view = renderWithClient(<SystemHealth params={{}} />);
    await userEvent.click(await screen.findByRole("button", { name: "Case details by CNR: details" }));
    navigate(view, <SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await waitFor(() => expect((window.history.state as Record<string, unknown> | null)?.__aslmsOverlay).toBe("api=cnr"));
    await userEvent.click(within(dialog).getByRole("button", { name: /close/i }));
    expect(nav.back).toHaveBeenCalledTimes(1);
    window.history.replaceState(null, "", window.location.href);
    navigate(view, <SystemHealth params={{ api: "cnr", tab: "docs" }} />);
    await userEvent.click(await screen.findByRole("button", { name: /close/i }));
    expect(nav.replace).toHaveBeenCalledWith("/system");
  });

  it("the console has four tabs, a shared link opens its tab, and the token card opens ?api=token with three", async () => {
    consoleRoutes();
    const view = renderWithClient(<SystemHealth params={{ api: "cnr", tab: "history" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    const tabs = (await within(dialog).findAllByRole("tab")).map((t) => t.textContent);
    expect(tabs).toEqual(["Request", "Response", "History", "Documentation"]);
    expect(within(dialog).getByRole("tab", { name: "History" })).toHaveAttribute("aria-selected", "true");
    expect(await within(dialog).findByRole("table", { name: "The last 7 days" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("tab", { name: "Documentation" }));
    expect(window.location.search).toBe("?api=cnr&tab=docs");
    navigate(view, <SystemHealth params={{}} />);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "Access token: details" }));
    expect(nav.push).toHaveBeenCalledWith("/system?api=token&tab=token");
    navigate(view, <SystemHealth params={{ api: "token", tab: "token" }} />);
    const token = await screen.findByRole("dialog", { name: "Access token" });
    expect((await within(token).findAllByRole("tab")).map((t) => t.textContent)).toEqual(["Token", "Request", "Documentation"]);
  });
});

describe("the Request tab", () => {
  it("renders the URL, the pre-filled field, the masked envelope and the plain string", async () => {
    consoleRoutes();
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    expect(await within(dialog).findByLabelText("Method and URL")).toHaveTextContent(
      "GET https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR",
    );
    const field = within(dialog).getByRole("textbox", { name: "cino" });
    expect(field).toHaveValue("GAHC010277142024");
    expect(field).toHaveAccessibleDescription(/from data ASLMS holds · mandatory/);
    expect(within(dialog).getByLabelText("The plain string")).toHaveTextContent("cino=GAHC010277142024");
    const envelope = within(dialog).getByRole("table", { name: "Query parameters (the envelope)" });
    expect(within(envelope).getByText("AS…")).toBeInTheDocument();
    expect(within(envelope).getByText("encrypted, 44 characters, not shown")).toBeInTheDocument();
    expect(within(dialog).getByText("Bearer ‹access token, not shown›")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("cURL template")).toHaveTextContent("<ACCESS_TOKEN>");
  });

  it("editing calls the preview once 400 ms after typing stops and updates the plain string; Reset restores", async () => {
    let previews = 0;
    const api = consoleRoutes({
      [`POST ${BASE}/napix/cnr/preview`]: (call: { body: { values: { cino: string } } }) => {
        previews += 1;
        return { ...consoleOf(), plain: `cino=${call.body.values.cino}`, plain_sha256: "b".repeat(64) };
      },
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    const field = await within(dialog).findByRole("textbox", { name: "cino" });
    await userEvent.clear(field);
    await userEvent.type(field, "GAHC010118832025");
    expect(previews).toBe(0);
    await waitFor(() => expect(within(dialog).getByLabelText("The plain string")).toHaveTextContent("cino=GAHC010118832025"));
    expect(previews).toBe(1);
    expect(api.calls.find((c) => c.path.endsWith("/preview"))!.body).toEqual({ values: { cino: "GAHC010118832025" } });
    expect(field).toHaveAccessibleDescription(/edited by you/);
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset to the sample" }));
    expect(field).toHaveValue("GAHC010277142024");
    expect(within(dialog).getByLabelText("The plain string")).toHaveTextContent("cino=GAHC010277142024");
  });

  it("an empty name with its hint keeps Send disabled, a 422 shows the field's message and a 429 the wait", async () => {
    const hidden = consoleOf({
      fields: [{ ...consoleOf().fields[0]!, value: "", prefilled: false, source: "empty", hint: "Type a CNR (the held sample belongs to a case you cannot see)" }],
      plain: "cino=‹type a CNR›",
      plain_complete: false,
      request_token: null,
    });
    consoleRoutes({
      [`GET ${BASE}/napix/cnr/console`]: hidden,
      [`POST ${BASE}/napix/cnr/preview`]: json(422, { detail: { code: "invalid_input", message: "x", errors: { cino: "A CNR is 4 letters and 12 digits; one CNR per send" } } }),
      [`POST ${BASE}/napix/cnr/test`]: json(429, { detail: { code: "test_too_soon", message: "too soon", retry_after: 42 } }, { "retry-after": "42" }),
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    const field = await within(dialog).findByRole("textbox", { name: "cino" });
    expect(field).toHaveAccessibleDescription(/cannot see/);
    const send = within(dialog).getByRole("button", { name: "Send · 1 court call" });
    expect(send).toBeDisabled();
    expect(send).toHaveAccessibleDescription("Type every value first");
    await userEvent.type(field, "BAD");
    expect(await within(dialog).findByText("A CNR is 4 letters and 12 digits; one CNR per send")).toBeInTheDocument();
    expect(send).toBeDisabled();
    expect(send).toHaveAccessibleDescription("Correct the values marked first");
  });

  it("a 429 on Send shows the wait", async () => {
    consoleRoutes({
      [`POST ${BASE}/napix/cnr/test`]: json(429, { detail: { code: "test_too_soon", message: "too soon", retry_after: 42 } }, { "retry-after": "42" }),
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await within(dialog).findByRole("textbox", { name: "cino" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send · 1 court call" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Next test possible in 42 s.");
  });

  it("Send is disabled with the reason when the switch is off", async () => {
    consoleRoutes({}, summary(false));
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await within(dialog).findByRole("textbox", { name: "cino" });
    expect(within(dialog).getByRole("button", { name: "Send · 1 court call" })).toBeDisabled();
  });
});

describe("Send and the Response tab", () => {
  it("Send posts once with the form's values and the Response tab opens with the answer", async () => {
    let posts = 0;
    let release: (v: Response) => void = () => {};
    const api = consoleRoutes({
      [`POST ${BASE}/napix/cnr/test`]: () => {
        posts += 1;
        return new Promise<Response>((r) => (release = r));
      },
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await within(dialog).findByRole("textbox", { name: "cino" });
    const send = within(dialog).getByRole("button", { name: "Send · 1 court call" });
    fireEvent.click(send);
    fireEvent.click(send);
    expect(posts).toBe(1);
    expect(api.calls.find((c) => c.path.endsWith("/test"))!.body).toEqual({ values: { cino: "GAHC010277142024" } });
    expect(within(dialog).getByText("Sending… (up to 30 s)")).toBeInTheDocument();
    await act(async () => release(json(200, sendResult())));
    expect(await within(dialog).findByText("Answered")).toBeInTheDocument();
    expect(within(dialog).getByRole("tab", { name: "Response" })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByText("X-RateLimit-Limit 1000 · X-RateLimit-Remaining 811")).toBeInTheDocument();
    expect(within(dialog).getByText("verified")).toBeInTheDocument();
    expect(within(dialog).getByText("Shown, not saved to cases. Use Search to add a case.")).toBeInTheDocument();
    // paths not in the field inventory: a warning notice
    const notice = within(dialog).getByText("Not in the field inventory — report it").closest("[role='status']")!;
    expect(notice).toHaveAttribute("data-tone", "warning");
    expect(within(notice as HTMLElement).getByText("brand_new_field")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "POST" && c.path.endsWith("/test"))).toHaveLength(1);
  });

  it("the full answer is fetched only when expanded (and then audited by the server)", async () => {
    const api = consoleRoutes({
      [`POST ${BASE}/napix/cnr/test`]: sendResult(),
      [`GET ${BASE}/napix/cnr/response`]: RAW,
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await within(dialog).findByRole("textbox", { name: "cino" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send · 1 court call" }));
    const section = await within(dialog).findByRole("button", { name: "Full answer (JSON)" });
    expect(api.calls.some((c) => c.path.includes("/response"))).toBe(false);
    await userEvent.click(section);
    expect(await within(dialog).findByLabelText("Full answer (JSON)")).toHaveTextContent('"cino": "GAHC010118832025"');
    const call = api.calls.find((c) => c.path.includes("/response"))!;
    expect(call.path).toBe(`${BASE}/napix/cnr/response?source=send&response_id=0192f000-0000-7000-8000-000000000001`);
  });

  it("without cases.view_all the full answer section says it is shown only to users who can see every case", async () => {
    const api = consoleRoutes({
      [`GET ${BASE}/napix/cnr/console`]: consoleOf({
        full_answer_allowed: false,
        full_answer_note: "The full answer is shown only to users who can see every case",
        last_send: {
          at: "2026-10-21T14:33:00+05:30", by: "person", recorded: true, edited: false, ok: true, answered: true,
          status: "ok", reason: "The court answered", method: "GET",
          url: "https://delhigw.napix.gov.in/nic/ecourts/hc-cnr-api/CNR", plain: "cino=GAHC010277142024",
          params_sha256: "a".repeat(64), http_status: 200, http_meaning: "Everything is normal", napix_status: null,
          napix_meaning: null, error_family: null, duration_ms: 800, attempts: 1, remaining: 800,
          rate_limit: { limit: 1000, remaining: 800 }, window_reset_at: "2026-10-21T14:34:00+05:30",
          token_verified: true, summary: null, structure: null, inventory_diff: null,
          response_id: "0192f000-0000-7000-8000-000000000001", response_available: true, same_plain_as_form: true,
        },
      }),
    });
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "response" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    expect(await within(dialog).findByText("a person")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Full answer (JSON)" }));
    expect(within(dialog).getByText("The full answer is shown only to users who can see every case")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.includes("/response"))).toBe(false);
    await userEvent.click(within(dialog).getByRole("tab", { name: "Request" }));
    expect(within(dialog).getByText("The last send used the same plain string: yes")).toBeInTheDocument();
  });

  it("Help opens the specification at the API's page in a new tab", async () => {
    consoleRoutes();
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "docs" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    const help = await within(dialog).findByRole("link", { name: "NAPIX documentation for this API" });
    expect(help).toHaveAttribute("href", "/api/backend/admin/system-health/docs/hc_spec#page=12");
    expect(help).toHaveAttribute("target", "_blank");
    expect(await within(dialog).findByRole("link", { name: "6.1 Search by CNR API (page 12)" })).toHaveAttribute("target", "_blank");
    expect(within(dialog).getByRole("table", { name: "Status codes" })).toBeInTheDocument();
  });

  it("Send is the modal's only primary and Check services again the page's", async () => {
    consoleRoutes();
    renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Case details by CNR" });
    await within(dialog).findByRole("textbox", { name: "cino" });
    const inModal = dialog.querySelectorAll("button[data-variant='primary']");
    expect(inModal).toHaveLength(1);
    expect(inModal[0]).toHaveTextContent("Send · 1 court call");
    const all = [...document.querySelectorAll("button[data-variant='primary']")].filter((b) => !dialog.contains(b));
    expect(all).toHaveLength(1);
    expect(all[0]).toHaveTextContent("Check services again");
  });

  it("under reduced motion the console closes at once", async () => {
    stubMotion(true);
    consoleRoutes();
    const view = renderWithClient(<SystemHealth params={{ api: "cnr", tab: "request" }} />);
    await screen.findByRole("dialog", { name: "Case details by CNR" });
    navigate(view, <SystemHealth params={{}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector("[data-closing='true']")).toBeNull();
  });
});

describe("the Access token card and modal", () => {
  it("the card reads the token on open without a POST and shows its state in words", async () => {
    const api = consoleRoutes();
    renderWithClient(<SystemHealth params={{}} />);
    const card = await screen.findByTestId("token-card");
    expect(await within(card).findByText("Held · 42 minutes left")).toBeInTheDocument();
    expect(card.querySelector("[data-lead='lead']")!.textContent).toBe("Working");
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it.each([
    [tokenState(true, { status: "warn", shared_store: false, held: false, ttl_seconds: null }), "Needs attention", "No shared token store — every court call's client obtains its own token"],
    [tokenState(true, { status: "down", held: false, ttl_seconds: null }), "Not working", "No token held — the next court call obtains one (1 token request)"],
    [tokenState(false, { status: "unknown", held: false, ttl_seconds: null }), "Not known", "Court calls are switched off on this server"],
    [tokenState(true, { renewing_soon: true, ttl_seconds: 40 }), "Working", "About to be renewed (under 60 s left)"],
  ])("each status reads in words", async (token, word, line) => {
    consoleRoutes({ [`GET ${BASE}/token`]: token });
    renderWithClient(<SystemHealth params={{}} />);
    const card = await screen.findByTestId("token-card");
    expect(await within(card).findByText(line)).toBeInTheDocument();
    expect(card.querySelector("[data-lead='lead']")!.textContent).toBe(word);
  });

  it("the Token tab lists the facts; Check token shows its cost, posts once and shows the outcome", async () => {
    let posts = 0;
    const api = consoleRoutes({
      [`POST ${BASE}/token/check`]: () => {
        posts += 1;
        return { ok: true, http_status: 200, outcome: "obtained", duration_ms: 300, expires_in: 3600, rate_limit: { limit: null, remaining: null }, token: tokenState(true, { check: { allowed: false, reason: "The token was checked a moment ago; the next check is possible in 600 s", next_allowed_at: null } }) };
      },
    });
    renderWithClient(<SystemHealth params={{ api: "token", tab: "token" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Access token" });
    expect(await within(dialog).findByText("Yes — 14:31, Case details by CNR, HTTP 200")).toBeInTheDocument();
    expect(within(dialog).getByText("The token value is never shown.")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0);
    const check = within(dialog).getByRole("button", { name: "Check token · 1 token request" });
    fireEvent.click(check);
    fireEvent.click(check);
    expect(posts).toBe(1);
    expect(await within(dialog).findByText("Token request: obtained")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Check token · 1 token request" })).toBeDisabled();
    const help = within(dialog).getByRole("link", { name: "NAPIX documentation for the access token" });
    expect(help).toHaveAttribute("href", "/api/backend/admin/system-health/docs/subscriber_manual#page=10");
  });

  it("Check token shows the wait when refused", async () => {
    consoleRoutes({
      [`POST ${BASE}/token/check`]: json(429, { detail: { code: "check_too_soon", message: "x", retry_after: 540 } }, { "retry-after": "540" }),
    });
    renderWithClient(<SystemHealth params={{ api: "token", tab: "request" }} />);
    const dialog = await screen.findByRole("dialog", { name: "Access token" });
    expect(await within(dialog).findByLabelText("cURL template")).toHaveTextContent("<CLIENT_KEY>:<CLIENT_SECRET>");
    await userEvent.click(within(dialog).getByRole("button", { name: "Check token · 1 token request" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The token was checked a moment ago. Next check possible in 9 minutes.");
  });
});
