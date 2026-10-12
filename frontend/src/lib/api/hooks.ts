"use client";

import { useQuery } from "@tanstack/react-query";

import { apiCasePath, refPath } from "../refs";
import { api } from "./client";
import type {
  CaseDetail,
  CaseOwnershipView,
  CaseType,
  InboxCountsList,
  Me,
  OfficeOut,
  RecipientList,
  ReferenceLabels,
  ScoringSettings,
} from "./types";

export const ME_KEY = ["me"] as const;

/** The signed-in login, its memberships and the union of its functions (`GET /me`). */
export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: () => api<Me>("/me"), staleTime: 60_000 });
}

/** The database's labels of user types, office kinds and ticket kinds (`GET /reference/labels`). */
export function useLabels() {
  return useQuery({
    queryKey: ["reference", "labels"],
    queryFn: () => api<ReferenceLabels>("/reference/labels"),
    staleTime: 10 * 60_000,
  });
}

export function labelOf(list: { code: string; label: string }[] | undefined, code: string | null | undefined): string {
  if (!code) return "—";
  return list?.find((x) => x.code === code)?.label ?? code;
}

/** The active departments (`GET /custody/recipients` without a department), for department pickers. */
export function useDepartments(enabled = true) {
  return useQuery({
    queryKey: ["departments"],
    queryFn: () => api<RecipientList>("/custody/recipients"),
    staleTime: 10 * 60_000,
    enabled,
  });
}

/** The officers and units of one department (`GET /custody/recipients?department=`), for the allot fields. */
export function useDepartmentPeople(department: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["departments", department, "people"],
    queryFn: () => api<RecipientList>("/custody/recipients", { query: { department, limit: 200 } }),
    staleTime: 5 * 60_000,
    enabled: enabled && !!department,
  });
}

/** The High Court's active case types (`GET /reference/case-types`). */
export function useCaseTypes(enabled = true) {
  return useQuery({
    queryKey: ["reference", "case-types"],
    queryFn: () => api<CaseType[]>("/reference/case-types"),
    staleTime: 60 * 60_000,
    enabled,
  });
}

export const INBOX_KEY = ["inbox"] as const;

/** The inbox counters, one block per department (`GET /inbox/counts`, or one department with `office`). */
export function useInboxCounts(office?: string | null, enabled = true) {
  return useQuery({
    queryKey: [...INBOX_KEY, "counts", office ?? null],
    queryFn: () => api<InboxCountsList>("/inbox/counts", { query: { office: office ?? undefined } }),
    enabled,
  });
}

/** The key of everything read for one case page (overview, ownership, tabs). */
export function caseKey(ref: string) {
  return ["case", refPath(ref)] as const;
}

/** A case's overview (`GET /cases/{ref}`). */
export function useCase(ref: string) {
  return useQuery({
    queryKey: [...caseKey(ref), "overview"],
    queryFn: () => api<CaseDetail>(apiCasePath(ref)),
  });
}

/** A case's ownership and the actions the caller may take (`GET /cases/{ref}/ownership`); 404 when not visible. */
export function useOwnership(ref: string, enabled = true) {
  return useQuery({
    queryKey: [...caseKey(ref), "ownership"],
    queryFn: () => api<CaseOwnershipView>(apiCasePath(ref, "ownership")),
    enabled,
  });
}

/** The active offices of the caller's `users.view` scope, by path (`GET /admin/offices`), for office pickers. */
export function useScopedOffices(enabled = true) {
  return useQuery({
    queryKey: ["admin", "offices", "scope"],
    queryFn: () => api<OfficeOut[]>("/admin/offices"),
    staleTime: 10 * 60_000,
    enabled,
  });
}

export const MAPPING_KEY = ["mapping"] as const;
export const SCORING_KEY = [...MAPPING_KEY, "scoring"] as const;

/** The current scoring settings (`GET /admin/scoring-settings`; State-wide, read-only without `admin.scoring`). */
export function useScoringSettings(enabled = true) {
  return useQuery({
    queryKey: [...SCORING_KEY, "current"],
    queryFn: () => api<ScoringSettings>("/admin/scoring-settings"),
    enabled,
  });
}
