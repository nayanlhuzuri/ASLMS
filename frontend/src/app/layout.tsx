// Inter, self-hosted (design portal-ui-redesign, decision 12): served from the portal, so `font-src 'self'` stays
import "@fontsource-variable/inter/wght.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./globals.css";

import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "@/components/Providers";
import { DEFAULT_LOCALE, htmlAttributes } from "@/lib/i18n";
import { T } from "@/lib/messages";

export const metadata: Metadata = {
  title: { default: `${T.portal} — ${T.portalLong}`, template: `%s · ${T.portal}` },
  description: `${T.portalLong}, ${T.owner}`,
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // reading the request headers renders every page per request, so Next.js puts the CSP nonce on its scripts
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  // the page's language and direction come from the locale (decision 27): `lang="en" dir="ltr"` today
  const { lang, dir } = htmlAttributes(DEFAULT_LOCALE);
  return (
    <html lang={lang} dir={dir}>
      <body data-nonce-applied={nonce ? "true" : undefined}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
