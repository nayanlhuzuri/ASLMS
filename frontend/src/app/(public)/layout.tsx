import type { ReactNode } from "react";

import s from "@/components/auth/auth.module.css";
import { T } from "@/lib/messages";

export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <main className={s.page} id="main">
      <div className={s.card}>
        <div className={s.brand}>
          <strong>{T.portal}</strong>
          <span>
            {T.portalLong} · {T.court}
          </span>
        </div>
        {children}
      </div>
    </main>
  );
}
