import { InboxFrame } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-inbox-simplify, decision 1: My Cases
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxFrame tab="mine" params={plainParams(await searchParams)} />;
}
