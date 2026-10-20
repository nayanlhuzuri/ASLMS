import { InboxFrame } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxFrame tab="working" params={plainParams(await searchParams)} />;
}
