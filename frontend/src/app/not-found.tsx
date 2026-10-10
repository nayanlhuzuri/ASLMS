import Link from "next/link";

import { T } from "@/lib/messages";

export default function NotFound() {
  return (
    <main id="main" style={{ padding: 48, maxWidth: 640, margin: "0 auto" }}>
      <h1>{T.notFound}</h1>
      <p>{T.notFoundText}</p>
      <Link href="/">{T.goHome}</Link>
    </main>
  );
}
