// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { errorText } from "@/lib/messages";

import { clientAddress, upstreamHeaders } from "./api";

function request(headers: Record<string, string>): Request {
  return new Request("http://portal.test/api/session/login", { headers });
}

afterEach(() => {
  delete process.env.TRUST_PROXY_HEADERS;
});

describe("clientAddress (design deployment-checklist, decision 8)", () => {
  it("takes the rightmost X-Forwarded-For entry behind the proxy", () => {
    process.env.TRUST_PROXY_HEADERS = "true";
    expect(clientAddress(request({ "x-forwarded-for": "192.0.2.7" }))).toBe("192.0.2.7");
    expect(clientAddress(request({ "x-forwarded-for": "::ffff:192.0.2.8" }))).toBe("192.0.2.8");
  });

  it("ignores a forged leftmost entry", () => {
    process.env.TRUST_PROXY_HEADERS = "true";
    const r = request({ "x-forwarded-for": "1.2.3.4, 198.51.100.20" });
    expect(clientAddress(r)).toBe("198.51.100.20");
  });

  it("drops the x-real-ip fallback", () => {
    process.env.TRUST_PROXY_HEADERS = "true";
    expect(clientAddress(request({ "x-real-ip": "1.2.3.4" }))).toBeNull();
  });

  it("forwards no address without the proxy", () => {
    expect(clientAddress(request({ "x-forwarded-for": "1.2.3.4" }))).toBeNull();
    process.env.TRUST_PROXY_HEADERS = "false";
    expect(clientAddress(request({ "x-forwarded-for": "1.2.3.4" }))).toBeNull();
    const headers = upstreamHeaders({ userAgent: "UA", forwardedFor: clientAddress(request({ "x-forwarded-for": "1.2.3.4" })) });
    expect(headers.get("x-forwarded-for")).toBeNull();
  });
});

describe("the proxy's answers", () => {
  it("has a text for throttled", () => {
    const text = errorText(new ApiError(429, "throttled", "x", { retry_after: 60 }));
    expect(text).toMatch(/Too many requests from this address/);
  });
});

describe("the System health refusals (design api-health-checker-followups, decisions 6 and 7)", () => {
  it("has a text for a person's other test still running", () => {
    const text = errorText(new ApiError(409, "user_test_running", "x"));
    expect(text).toBe("Your other test is still running. Try again when it has finished.");
  });
  it("has a text for a connectivity check or connection test running", () => {
    const text = errorText(new ApiError(409, "check_running", "x"));
    expect(text).toBe("A connectivity check or a test of the connection is running. Try again in a moment.");
  });
});
