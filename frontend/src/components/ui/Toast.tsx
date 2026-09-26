"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { errorMessage } from "@/lib/api";
import s from "./ui.module.css";

type Kind = "success" | "error";
interface ToastItem {
  id: number;
  kind: Kind;
  text: string;
}

interface ToastApi {
  success: (text: string) => void;
  error: (e: unknown) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);

  const push = useCallback(
    (kind: Kind, text: string) => {
      const id = ++seq.current;
      setItems((xs) => [...xs.slice(-3), { id, kind, text }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 9000 : 5000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (text) => push("success", text),
      error: (e) => push("error", typeof e === "string" ? e : errorMessage(e)),
    }),
    [push],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      <div className={`${s.toasts} no-print`} aria-live="polite" aria-relevant="additions" role="status">
        {items.map((t) => (
          <div key={t.id} className={`${s.toast} ${t.kind === "error" ? s.toastError : ""}`}>
            <span className="sr-only">{t.kind === "error" ? "Error:" : "Done:"}</span>
            <span className={s.toastText}>{t.text}</span>
            <button type="button" className={s.toastClose} onClick={() => dismiss(t.id)} aria-label="Dismiss message">
              Close
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast outside ToastProvider");
  return v;
}
