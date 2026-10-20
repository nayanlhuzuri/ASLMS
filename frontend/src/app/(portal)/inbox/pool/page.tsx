import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";
import { OLD_INBOX_REDIRECTS } from "@/lib/routes";

type SP = Promise<Record<string, string | string[] | undefined>>;

/** Decision 10.4 of portal-ui-redesign: the old address, redirected on the client with its query string. */
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Redirect to={OLD_INBOX_REDIRECTS["/inbox/pool"]!} params={plainParams(await searchParams)} />;
}
