import { redirect } from "next/navigation";

import { UsersList } from "@/components/admin/Users";
import { plainParams, queryString } from "@/lib/params";

type SP = Promise<Record<string, string | string[] | undefined>>;

// design case-workspace-admin, decision 23: `?user=new` opens the new-user side panel; design portal-ui-polish-2,
// decision 31: the old `?user=<id>` address of a person redirects to `/admin/users/<id>`, the query string kept
export default async function Page({ searchParams }: { searchParams: SP }) {
  const params = plainParams(await searchParams);
  const { user, ...rest } = params;
  if (user && user !== "new") redirect(`/admin/users/${encodeURIComponent(user)}${queryString(rest)}`);
  return <UsersList params={params} />;
}
