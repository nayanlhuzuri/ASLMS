import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

/** `/inbox`: Working on (design portal-ui-redesign, decision 5). */
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Redirect to="/inbox/working" params={plainParams(await searchParams)} />;
}
