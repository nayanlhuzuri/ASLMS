import type { Metadata } from "next";

import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.auth.codeTitle };

/**
 * The old code-step address (design home-page, decision 2): old links and bookmarks land on the home page's code step,
 * `/login?step=code`, keeping `next`. A client redirect, so the route still answers 200.
 */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  return <Redirect to="/login?step=code" params={plainParams(await searchParams)} />;
}
