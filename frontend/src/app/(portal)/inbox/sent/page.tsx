import { InboxFrame } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxFrame tab="sent" params={plainParams(await searchParams)} />;
}
