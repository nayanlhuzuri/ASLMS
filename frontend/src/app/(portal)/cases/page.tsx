import { InboxIndex } from "@/components/inbox/InboxFrame";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// `/cases` (the "Case inbox" crumb above a case page; design case-inbox-merge, decision 12): the first Case inbox tab
// the login may open, else Search
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <InboxIndex params={plainParams(await searchParams)} />;
}
