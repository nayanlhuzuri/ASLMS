import type { ReactNode } from "react";

import { CaseFrame } from "@/components/case/CaseFrame";

// `[ref]` is the case's ref_no in the dash form (the mail links), an id or a CNR; the API resolves each
export default async function CaseLayout({ children, params }: { children: ReactNode; params: Promise<{ ref: string }> }) {
  const { ref } = await params;
  return <CaseFrame caseRef={decodeURIComponent(ref)}>{children}</CaseFrame>;
}
