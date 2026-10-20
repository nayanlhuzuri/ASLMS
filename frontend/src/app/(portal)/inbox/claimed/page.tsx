import { ClaimedRedirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

/** Decision 10.4 of portal-ui-redesign: Department cases for a whole-department reader, else Working on. */
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ClaimedRedirect params={plainParams(await searchParams)} />;
}
