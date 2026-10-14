import type { Metadata } from "next";

import { AuditSearch } from "@/components/audit/AuditSearch";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.audit.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <AuditSearch params={plainParams(await searchParams)} />;
}
