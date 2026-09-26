"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import type { Me, Office } from "@/lib/types";

interface MeState {
  me: Me;
  setMe: (me: Me) => void;
  reload: () => Promise<void>;
}

const Ctx = createContext<MeState | null>(null);

export function MeProvider({ children, fallback }: { children: ReactNode; fallback: (error: string | null, retry: () => void) => ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setError(null);
      setMe(await api.get<Me>("/me"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const value = useMemo(() => (me ? { me, setMe, reload } : null), [me, reload]);
  if (!value) return <>{fallback(error, () => void reload())}</>;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useMe(): MeState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useMe outside MeProvider");
  return v;
}

/** Offices list, loaded once per page view and shared. */
let officeCache: Promise<Office[]> | null = null;

export function loadOffices(force = false): Promise<Office[]> {
  if (!officeCache || force) {
    officeCache = api.get<Office[]>("/offices").catch((e: unknown) => {
      officeCache = null;
      throw e;
    });
  }
  return officeCache;
}

export function useOffices(): { offices: Office[]; departments: Office[]; byId: Map<string, Office>; reload: () => void } {
  const [offices, setOffices] = useState<Office[]>([]);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    loadOffices(tick > 0)
      .then((o) => {
        if (alive) setOffices(o);
      })
      .catch(() => {
        /* lists stay empty; the page shows its own errors */
      });
    return () => {
      alive = false;
    };
  }, [tick]);
  return useMemo(
    () => ({
      offices,
      departments: offices.filter((o) => o.kind === "department" && o.is_active),
      byId: new Map(offices.map((o) => [o.id, o])),
      reload: () => setTick((t) => t + 1),
    }),
    [offices],
  );
}
