import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AdminFrame } from "@/components/admin/AdminFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.admin.title };

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminFrame>{children}</AdminFrame>;
}
