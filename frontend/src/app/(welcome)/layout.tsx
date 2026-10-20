import type { ReactNode } from "react";

import s from "@/components/auth/auth.module.css";
import { BrandLockup } from "@/components/shell/Brand";
import { T } from "@/lib/messages";

export default function WelcomeLayout({ children }: { children: ReactNode }) {
  return (
    <main className={s.page} id="main">
      <div className={`${s.card} ${s.wide}`}>
        <div className={s.brand}>
          <BrandLockup />
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
