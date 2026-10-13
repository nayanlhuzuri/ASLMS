import type { Metadata } from "next";

import { CauseList } from "@/components/causelist/CauseList";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.causelist.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  const params = plainParams(await searchParams);
  return <CauseList key={`${params.date ?? ""}|${params.q ?? ""}`} params={params} />;
}
