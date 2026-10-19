/**
 * Web-server settings (design portal-shell, decisions 3, 6 and 20; deployment-checklist, decision 8). The Compose
 * `web` service passes only these six variables; local `npm run dev` falls back to the defaults. Read on every call so
 * tests can change them. `trustProxyHeaders` is true only behind the proxy, which overwrites `X-Forwarded-For`.
 */
export interface ServerConfig {
  apiBaseUrl: string;
  portalBaseUrl: string;
  cookieSecure: boolean;
  refreshTokenDays: number;
  relayTimeoutMs: number;
  trustProxyHeaders: boolean;
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
    trustProxyHeaders: (process.env.TRUST_PROXY_HEADERS ?? "false").trim().toLowerCase() === "true",
  };
}
