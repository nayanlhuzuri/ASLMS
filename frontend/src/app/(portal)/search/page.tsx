import type { Metadata } from "next";

import { Search } from "@/components/search/Search";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.search.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  const params = plainParams(await searchParams);
  return <Search key={`${params.tab ?? ""}|${params.q ?? ""}`} params={params} />;
}
