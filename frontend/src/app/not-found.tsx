import Link from "next/link";

export default function NotFound() {
  return (
    <main style={{ maxWidth: 560, margin: "96px auto", padding: "0 16px", display: "flex", flexDirection: "column", gap: 14 }}>
      <h1>Page not found</h1>
      <p className="muted">The address may be mistyped, or the page may have moved.</p>
      <p>
        <Link href="/" style={{ fontWeight: 600 }}>
          Go to the dashboard
        </Link>
      </p>
    </main>
  );
}
