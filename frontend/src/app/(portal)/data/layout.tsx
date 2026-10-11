import type { Metadata } from "next";
import type { ReactNode } from "react";

import { DataFrame } from "@/components/data/DataFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.data.title };

export default function DataLayout({ children }: { children: ReactNode }) {
  return <DataFrame>{children}</DataFrame>;
}
