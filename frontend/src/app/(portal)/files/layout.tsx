import type { Metadata } from "next";
import type { ReactNode } from "react";

import { FilesFrame } from "@/components/files/FilesFrame";
import { T } from "@/lib/messages";

export const metadata: Metadata = { title: T.files.title };

export default function FilesLayout({ children }: { children: ReactNode }) {
  return <FilesFrame>{children}</FilesFrame>;
}
