import { InboxIndex } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

/** `/inbox`: the first tab the login may open, else Search (design case-inbox-merge, decision 7). */
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxIndex params={plainParams(await searchParams)} />;
}
