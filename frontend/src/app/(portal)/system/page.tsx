import type { Metadata } from "next";

import { SystemHealth } from "@/components/system/SystemHealth";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.system.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <SystemHealth params={plainParams(await searchParams)} />;
}
