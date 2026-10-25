import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";
import { OLD_CASES_REDIRECTS } from "@/lib/routes";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-inbox-merge, decision 12: the Cases list tab now lives in the Case inbox; the query string is kept
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Redirect to={OLD_CASES_REDIRECTS["/cases/with-me"]!} params={plainParams(await searchParams)} />;
}
