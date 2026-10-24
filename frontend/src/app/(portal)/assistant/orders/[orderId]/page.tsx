import type { Metadata } from "next";

import { CourtOrderView } from "@/components/assistant/CourtOrderView";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.assistant.courtRecord };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ params, searchParams }: { params: Promise<{ orderId: string }>; searchParams: SP }) {
  const { orderId } = await params;
  const query = plainParams(await searchParams);
  return <CourtOrderView orderId={decodeURIComponent(orderId)} messageId={query.m ?? null} />;
}
