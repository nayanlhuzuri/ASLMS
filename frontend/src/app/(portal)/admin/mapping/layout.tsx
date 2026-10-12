import type { Metadata } from "next";
import type { ReactNode } from "react";

import { MappingFrame } from "@/components/admin/mapping/MappingFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.mapping.title };

export default function MappingLayout({ children }: { children: ReactNode }) {
  return <MappingFrame>{children}</MappingFrame>;
}
