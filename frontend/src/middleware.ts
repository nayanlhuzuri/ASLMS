import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PAGES = ["/login", "/forgot"];

/**
 * Sends signed-out visitors (no refresh cookie) to the sign-in page. Only presence is checked here; the
 * backend validates every token. API routes answer 401 themselves, so they are not redirected.
 */
export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  if (PUBLIC_PAGES.some((p) => pathname === p || pathname.startsWith(`${p}/`))) return NextResponse.next();
  if (req.cookies.get("aslms_rt")?.value) return NextResponse.next();
  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.search = "";
  const next = `${pathname}${search}`;
  if (next && next !== "/") url.searchParams.set("next", next);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|icon.svg|robots.txt|fonts/).*)"],
};
