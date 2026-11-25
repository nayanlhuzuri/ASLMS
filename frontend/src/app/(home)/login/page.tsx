import type { Metadata } from "next";

import { HomePage } from "@/components/home/HomePage";
import { T } from "@/lib/messages";

/** The public home page with the sign-in form on it (design home-page, row 274, decision 1). */
export const metadata: Metadata = { title: { absolute: `${T.portal} — ${T.portalLong}` } };

export default function Page() {
  return <HomePage />;
}
