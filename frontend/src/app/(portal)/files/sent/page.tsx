import { Redirect } from "@/components/inbox/Redirects";
import { plainParams } from "@/lib/params";
import { OLD_FILES_REDIRECTS } from "@/lib/routes";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-workspace-admin, decision 3: the old address keeps working, with its query string
export default async function Page({ searchParams }: { searchParams: SP }) {
  return <Redirect to={OLD_FILES_REDIRECTS["/files/sent"]!} params={plainParams(await searchParams)} />;
}
