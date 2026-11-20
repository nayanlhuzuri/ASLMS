import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EXPORT_STORAGE_KEY } from "@/lib/insights";
import { FIELDS } from "@/test/insightsFixtures";
import { resetNav } from "@/test/nav";
import { browserApi, renderWithClient } from "@/test/render";

import { ExportDialog, fieldsFor, initialFields } from "./ExportDialog";

beforeEach(() => {
  resetNav("/insights");
  window.localStorage.clear();
  browserApi({ "GET /insights/fields": FIELDS });
});

function downloadHref(): URL {
  const link = screen.getByRole("link", { name: "Download" });
  return new URL(link.getAttribute("href")!, "http://x");
}

describe("the export dialog (design state-insights, decisions 27 and 33)", () => {
  it("ticks the default fields and sends them with the list's filters and sort", async () => {
    renderWithClient(<ExportDialog format="xlsx" params={{ kind: "contempt", sort: "registered" }} total={120} onClose={vi.fn()} />);
    expect(await screen.findByRole("checkbox", { name: /Case Number/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /ASLMS Reference Number/ })).not.toBeChecked();
    expect(screen.getByText("120 cases in this selection.")).toBeInTheDocument();
    const href = downloadHref();
    expect(href.pathname).toBe("/api/backend/insights/export");
    expect(href.searchParams.get("kind")).toBe("contempt");
    expect(href.searchParams.get("sort")).toBe("registered");
    expect(href.searchParams.get("format")).toBe("xlsx");
    expect(href.searchParams.get("fields")).toBe("case_no,cnr,petitioners,status,owning_department");
  });

  it("offers Link to the Case Page only for Excel", async () => {
    renderWithClient(<ExportDialog format="xlsx" params={{}} total={10} onClose={vi.fn()} />);
    const link = await screen.findByRole("checkbox", { name: /Link to the Case Page/ });
    await userEvent.click(link);
    expect(downloadHref().searchParams.get("fields")).toContain("link");
    await userEvent.click(within(screen.getByRole("radiogroup", { name: "Format" })).getByRole("radio", { name: "PDF" }));
    expect(screen.queryByRole("checkbox", { name: /Link to the Case Page/ })).toBeNull();
    expect(downloadHref().searchParams.get("fields")).not.toContain("link");
    expect(downloadHref().searchParams.get("format")).toBe("pdf");
  });

  it("warns before a PDF of more than 2,000 cases, and not for Excel", async () => {
    const { unmount } = renderWithClient(<ExportDialog format="pdf" params={{}} total={2500} onClose={vi.fn()} />);
    expect(await screen.findByText("The PDF holds the first 2,000 of 2,500 cases. Export to Excel for every case.")).toBeInTheDocument();
    unmount();
    renderWithClient(<ExportDialog format="pdf" params={{}} total={2000} onClose={vi.fn()} />);
    await screen.findByRole("checkbox", { name: /Case Number/ });
    expect(screen.queryByText(/The PDF holds the first/)).toBeNull();
  });

  it("keeps the choice in the browser on Download and starts from it next time", async () => {
    const onClose = vi.fn();
    const { unmount } = renderWithClient(<ExportDialog format="xlsx" params={{}} total={5} onClose={onClose} />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Bench or Judges/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Petitioners/ }));
    const link = screen.getByRole("link", { name: "Download" });
    link.addEventListener("click", (e) => e.preventDefault());
    await userEvent.click(link);
    expect(onClose).toHaveBeenCalled();
    expect(JSON.parse(window.localStorage.getItem(EXPORT_STORAGE_KEY)!)).toContain("coram");
    unmount();
    renderWithClient(<ExportDialog format="xlsx" params={{}} total={5} onClose={vi.fn()} />);
    expect(await screen.findByRole("checkbox", { name: /Bench or Judges/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Petitioners/ })).not.toBeChecked();
  });

  it("shows Applications Pending while interlocutory applications are inside their main case", async () => {
    const { unmount } = renderWithClient(<ExportDialog format="xlsx" params={{}} total={5} onClose={vi.fn()} />);
    expect(await screen.findByRole("checkbox", { name: "Applications Pending" })).toBeDisabled();
    unmount();
    renderWithClient(<ExportDialog format="xlsx" params={{ include_ia: "true" }} total={5} onClose={vi.fn()} />);
    await screen.findByRole("checkbox", { name: /Case Number/ });
    expect(screen.queryByRole("checkbox", { name: "Applications Pending" })).toBeNull();
  });

  it("no field chosen: no download", async () => {
    renderWithClient(<ExportDialog format="pdf" params={{}} total={5} onClose={vi.fn()} />);
    for (const name of [/Case Number/, /CNR/, /Petitioners/, /^18\. Status/, /Owning Department/]) {
      await userEvent.click(await screen.findByRole("checkbox", { name }));
    }
    expect(screen.queryByRole("link", { name: "Download" })).toBeNull();
    expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
  });

  it("the pure rules: defaults, the kept choice and the Excel-only field", () => {
    expect(initialFields(FIELDS, null)).toEqual(["case_no", "cnr", "petitioners", "status", "owning_department"]);
    expect(initialFields(FIELDS, ["coram", "gone"])).toEqual(["coram"]);
    expect(fieldsFor(FIELDS, ["link", "cnr"], "pdf")).toEqual(["cnr"]);
    expect(fieldsFor(FIELDS, ["link", "cnr"], "xlsx")).toEqual(["cnr", "link"]);
  });
});
