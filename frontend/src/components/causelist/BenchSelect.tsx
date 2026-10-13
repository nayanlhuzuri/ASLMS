"use client";

/**
 * The bench select (design portal-causelist, decisions 2 and 11): "All benches", then each bench of the day in court
 * order as "Court 6 · HONOURABLE MR. JUSTICE … · 53". A NAPIX bench writes `bench_id`; a court-wide file `list_id`.
 */
import { SelectField } from "@/components/ui";
import type { CauselistBench } from "@/lib/api/types";
import { benchValue } from "@/lib/causelist";
import { T } from "@/lib/messages";

export function benchLabel(b: CauselistBench): string {
  const label =
    b.label ?? (b.bench_id !== null ? T.causelist.benchNumber(b.bench_id) : T.causelist.courtWide);
  const shown = b.lists.length === 0 ? `${label} (${T.causelist.noListPublished})` : label;
  return T.causelist.benchOption(b.court_nos[0] ?? null, shown, b.entries);
}

export function BenchSelect({
  benches,
  value,
  onChange,
}: {
  benches: CauselistBench[];
  value: string;
  onChange: (value: string) => void;
}) {
  const options = [
    { value: "", label: T.causelist.allBenches },
    ...benches.filter((b) => benchValue(b)).map((b) => ({ value: benchValue(b), label: benchLabel(b) })),
  ];
  return (
    <SelectField label={T.causelist.bench} value={value} options={options} onChange={(e) => onChange(e.target.value)} />
  );
}
