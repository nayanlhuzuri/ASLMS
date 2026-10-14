import type { Metadata } from "next";

import { AuditEntry } from "@/components/audit/AuditEntry";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.audit.entryTitle };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AuditEntry id={id} />;
}
