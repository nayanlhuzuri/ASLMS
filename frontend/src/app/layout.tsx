import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/source-serif-4/400.css";
import "@fontsource/source-serif-4/600.css";
import "./globals.css";

import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "@/components/Providers";
import { T } from "@/lib/messages";

export const metadata: Metadata = {
  title: { default: `${T.portal} — ${T.portalLong}`, template: `%s · ${T.portal}` },
  description: `${T.portalLong}, ${T.court}`,
  robots: { index: false, follow: false },
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // reading the request headers renders every page per request, so Next.js puts the CSP nonce on its scripts
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en">
      <body data-nonce-applied={nonce ? "true" : undefined}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
