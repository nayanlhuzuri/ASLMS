import { OldInboxRedirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// an old address (design case-inbox-simplify, decision 15): one client redirect keeping the query string
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <OldInboxRedirect from="/cases/with-me" params={plainParams(await searchParams)} />;
}
