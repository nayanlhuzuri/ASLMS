import { fmtNumber } from "@/lib/format";
import { Button } from "./Button";
import s from "./ui.module.css";

export function Pagination({
  page,
  size,
  total,
  onPage,
  noun = "results",
}: {
  page: number;
  size: number;
  total: number;
  onPage: (p: number) => void;
  noun?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (total === 0) return null;
  const from = (page - 1) * size + 1;
  const to = Math.min(total, page * size);
  return (
    <nav className={`${s.pager} no-print`} aria-label="Pagination">
      <span>
        {fmtNumber(from)}–{fmtNumber(to)} of {fmtNumber(total)} {noun}
      </span>
      {pages > 1 ? (
        <div className={s.pagerButtons}>
          <Button small icon="chevronLeft" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            Previous
          </Button>
          <span style={{ alignSelf: "center" }}>
            Page {page} of {fmtNumber(pages)}
          </span>
          <Button small disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Next
          </Button>
        </div>
      ) : null}
    </nav>
  );
}
