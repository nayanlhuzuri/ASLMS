import { InboxFrame } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-inbox-simplify, decision 1: With Me
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxFrame tab="with-me" params={plainParams(await searchParams)} />;
}
