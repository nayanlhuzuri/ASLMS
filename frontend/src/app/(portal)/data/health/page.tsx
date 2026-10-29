import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";
import { OLD_DATA_REDIRECTS } from "@/lib/routes";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design data-collection-redesign, decisions 2 and 3: the old address keeps working, with its query string
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Redirect to={OLD_DATA_REDIRECTS["/data/health"]!} params={plainParams(await searchParams)} />;
}
