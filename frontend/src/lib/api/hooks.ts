"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "./client";
import type { Me, ReferenceLabels } from "./types";

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
