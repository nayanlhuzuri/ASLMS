import type { Metadata } from "next";

import { MyCalendar } from "@/components/calendar/MyCalendar";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.mycal.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <MyCalendar params={plainParams(await searchParams)} />;
}
