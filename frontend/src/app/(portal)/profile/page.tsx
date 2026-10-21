import type { Metadata } from "next";

import { ProfilePage } from "@/components/profile/Profile";
import { T } from "@/lib/messages";
import { plainParams } from "@/lib/params";

export const metadata: Metadata = { title: T.profile.title };

type SP = Promise<Record<string, string | string[] | undefined>>;

export default async function Page({ searchParams }: { searchParams: SP }) {
  return <ProfilePage params={plainParams(await searchParams)} />;
}
