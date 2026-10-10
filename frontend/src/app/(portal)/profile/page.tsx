import type { Metadata } from "next";

import { ProfilePage } from "@/components/profile/Profile";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.profile.title };

export default function Page() {
  return <ProfilePage />;
}
