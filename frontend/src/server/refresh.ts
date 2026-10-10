/**
 * Single-flight refresh (design portal-shell, decision 4). A rotated refresh token presented twice ends every
 * session of the login, so parallel requests carrying the same refresh token share one `/auth/refresh` call, and
 * its answer is remembered for 30 seconds for requests still carrying the old cookie. Keyed by the SHA-256 of the
 * token; in memory, one `web` process (several instances would need sticky sessions or a shared store).
 */
import { createHash } from "node:crypto";

import { ApiUnavailable, callApi, type ClientContext } from "./api";

export const REMEMBER_MS = 30_000;

export interface RefreshedTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export type RefreshResult =
  | { ok: true; tokens: RefreshedTokens }
  | { ok: false; status: number; code: string; message: string };

interface Entry {
  promise: Promise<RefreshResult>;
  settledAt?: number;
}

const entries = new Map<string, Entry>();

function keyOf(refreshToken: string): string {
  return createHash("sha256").update(refreshToken).digest("hex");
}

function prune(now: number): void {
  for (const [key, entry] of entries) {
    if (entry.settledAt !== undefined && now - entry.settledAt >= REMEMBER_MS) entries.delete(key);
  }
}

async function exchange(refreshToken: string, ctx: ClientContext): Promise<RefreshResult> {
  try {
    const answer = await callApi({
      method: "POST",
      path: "/auth/refresh",
      body: { refresh_token: refreshToken },
      ...ctx,
    });
    const data = answer.data as Partial<RefreshedTokens> & { detail?: { code?: string; message?: string } };
    if (answer.status === 200 && data?.access_token && data.refresh_token) {
      return {
        ok: true,
        tokens: {
          access_token: data.access_token,
          refresh_token: data.refresh_token,
          expires_in: Number(data.expires_in) || 1800,
        },
      };
    }
    return {
      ok: false,
      status: answer.status,
      code: data?.detail?.code || "refresh_invalid",
      message: data?.detail?.message || "the session has ended",
    };
  } catch (error) {
    if (error instanceof ApiUnavailable) {
      return { ok: false, status: 502, code: "api_unavailable", message: error.message };
    }
    throw error;
  }
}

export function refreshOnce(refreshToken: string, ctx: ClientContext = {}): Promise<RefreshResult> {
  const now = Date.now();
  prune(now);
  const key = keyOf(refreshToken);
  const existing = entries.get(key);
  if (existing) return existing.promise;
  const entry: Entry = {
    promise: exchange(refreshToken, ctx).then(
      (result) => {
        if (!result.ok && result.code === "api_unavailable") entries.delete(key);
        else entry.settledAt = Date.now();
        return result;
      },
      (error: unknown) => {
        entries.delete(key);
        throw error;
      },
    ),
  };
  entries.set(key, entry);
  return entry.promise;
}

/** Tests only: forget every remembered refresh. */
export function resetRefreshMemory(): void {
  entries.clear();
}

export function rememberedCount(): number {
  prune(Date.now());
  return entries.size;
}
