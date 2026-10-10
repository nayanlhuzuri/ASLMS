/**
 * Web-server settings (design portal-shell, decisions 3, 6 and 20). The Compose `web` service passes only these
 * five variables; local `npm run dev` falls back to the defaults. Read on every call so tests can change them.
 */
export interface ServerConfig {
  apiBaseUrl: string;
  portalBaseUrl: string;
  cookieSecure: boolean;
  refreshTokenDays: number;
  relayTimeoutMs: number;
}

function positive(value: string | undefined, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function serverConfig(): ServerConfig {
  return {
    apiBaseUrl: (process.env.API_BASE_URL || "http://localhost:8000").replace(/\/+$/, ""),
    portalBaseUrl: (process.env.PORTAL_BASE_URL || "http://localhost:3000").replace(/\/+$/, ""),
    cookieSecure: (process.env.COOKIE_SECURE ?? "true").trim().toLowerCase() !== "false",
    refreshTokenDays: positive(process.env.ASLMS_REFRESH_TOKEN_DAYS, 14),
    relayTimeoutMs: positive(process.env.RELAY_TIMEOUT_SECONDS, 120) * 1000,
  };
}
