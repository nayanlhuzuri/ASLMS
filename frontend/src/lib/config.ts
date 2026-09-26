"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { AppConfig } from "./types";

/** Portal-relevant backend settings (GET /config), loaded once per page view. */
let cache: Promise<AppConfig> | null = null;

export function loadConfig(): Promise<AppConfig> {
  if (!cache) {
    cache = api.get<AppConfig>("/config").catch((e: unknown) => {
      cache = null;
      throw e;
    });
  }
  return cache;
}

/** Fallbacks match the backend defaults until /config has answered. */
export const DEFAULT_CONFIG: AppConfig = {
  upload_max_mb: 25,
  allowed_upload_types: [".doc", ".docx", ".jpeg", ".jpg", ".pdf", ".png", ".tif", ".tiff"],
  napix_enabled: true,
  sourcetrace_enabled: true,
  score_strong_threshold: 0.85,
  score_possible_threshold: 0.5,
  app_env: "",
};

export function useConfig(): { config: AppConfig; loaded: boolean } {
  const [config, setConfig] = useState<AppConfig | null>(null);
  useEffect(() => {
    let alive = true;
    loadConfig()
      .then((c) => {
        if (alive) setConfig(c);
      })
      .catch(() => {
        /* keep defaults */
      });
    return () => {
      alive = false;
    };
  }, []);
  return { config: config ?? DEFAULT_CONFIG, loaded: config !== null };
}

/** "PDF, Word or image" style description of the allowed upload types. */
export function describeTypes(exts: string[]): string {
  const set = new Set(exts.map((e) => e.toLowerCase()));
  const parts: string[] = [];
  if (set.has(".pdf")) parts.push("PDF");
  if (set.has(".doc") || set.has(".docx")) parts.push("Word");
  if ([".jpg", ".jpeg", ".png", ".tif", ".tiff"].some((e) => set.has(e))) parts.push("image");
  return parts.length ? parts.join(", ").replace(/, ([^,]*)$/, " or $1") : exts.join(", ");
}
