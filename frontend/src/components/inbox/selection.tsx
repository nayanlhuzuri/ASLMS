"use client";

/**
 * The department a department-scoped screen is read for (design portal-cases, decision 4; kept by portal-ui-redesign,
 * decisions 5 and 6): `?department=CODE`, sent to the API as `office`. The selector lists the departments of
 * `/inbox/counts`; a holder of `cases.view_all` may also pick any active department and then reads it as the API
 * allows. Case claim and the Case inbox's Department cases share it.
 */
import { useRouter } from "next/navigation";

import { SelectField } from "@/components/ui";
import { useDepartments, useInboxCounts, useMe } from "@/lib/api/hooks";
import type { InboxCounts, Me } from "@/lib/api/types";
import { can } from "@/lib/can";
import { T } from "@/lib/messages";

export interface Selection {
  me: Me | undefined;
  department: string | null;
  block: InboxCounts | null | undefined;
  /** Every counts block of the caller's own departments. */
  blocks: InboxCounts[];
  options: { code: string; label: string }[];
  isPending: boolean;
  error: unknown;
  refetch: () => void;
}

/** The selected department and its counts block. */
export function useInboxSelection(requested: string | undefined): Selection {
  const me = useMe();
  const own = useInboxCounts(null, !!me.data);
  const viewAll = can(me.data, "cases.view_all");
  const all = useDepartments(viewAll);
  const blocks = own.data?.departments ?? [];
  const ownCodes = blocks.map((b) => b.office_code).filter((c): c is string => !!c);
  const wanted = requested ? requested.trim().toUpperCase() : null;
  const department = wanted ?? ownCodes[0] ?? null;
  const inOwn = !!department && ownCodes.includes(department);
  const other = useInboxCounts(department, !!department && !inOwn && own.isSuccess);
  const block = inOwn
    ? blocks.find((b) => b.office_code === department)
    : department
      ? other.data?.departments[0]
      : blocks[0];
  const names = new Map((all.data?.departments ?? []).map((d) => [d.code, d.name]));
  const codes = viewAll ? [...new Set([...ownCodes, ...(all.data?.departments ?? []).map((d) => d.code)])] : ownCodes;
  const options = codes.map((code) => ({ code, label: names.get(code) ? `${code} — ${names.get(code)}` : code }));
  return {
    me: me.data,
    department,
    block,
    blocks,
    options,
    isPending: me.isPending || own.isPending || (!!department && !inOwn && other.isPending),
    error: me.error ?? own.error ?? (inOwn ? null : other.error),
    refetch: () => {
      void own.refetch();
      if (!inOwn) void other.refetch();
    },
  };
}

/** Whether the selector shows: several departments, or a department other than the only one offered. */
export function showsSelector(sel: Selection): boolean {
  return sel.options.length > 1 || (sel.options.length === 1 && sel.department !== sel.options[0]!.code);
}

/** The department selector; choosing goes to `hrefFor(code)`. */
export function DepartmentSelect({ sel, hrefFor }: { sel: Selection; hrefFor: (code: string | null) => string }) {
  const router = useRouter();
  if (!showsSelector(sel)) return null;
  return (
    <div style={{ maxWidth: 360 }}>
      <SelectField
        label={T.inbox.department}
        options={sel.options.map((o) => ({ value: o.code, label: o.label }))}
        placeholder={sel.department ? undefined : T.inbox.chooseDepartment}
        value={sel.department ?? ""}
        onChange={(e) => router.push(hrefFor(e.target.value || null))}
      />
    </div>
  );
}
