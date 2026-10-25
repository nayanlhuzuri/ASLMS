import type { Metadata } from "next";
import type { ReactNode } from "react";

import { CasesFrame } from "@/components/files/FilesFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.files.title };

// design case-workspace-admin, decision 3: the Cases list beside the case page; static segments win over `[ref]`
export default function CasesListLayout({ children }: { children: ReactNode }) {
  return <CasesFrame>{children}</CasesFrame>;
}
