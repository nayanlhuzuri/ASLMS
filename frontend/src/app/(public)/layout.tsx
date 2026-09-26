import type { ReactNode } from "react";
import s from "./auth.module.css";

export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className={s.page}>
      <aside className={s.brand}>
        <div className={s.brandTitle}>
          Legal Case
          <br />
          Monitoring Portal
        </div>
        <div className={s.brandCaption}>Gauhati High Court</div>
        <p className={s.brandText}>
          Cases before the Gauhati High Court that concern the departments of the Government of Assam: cause lists, hearings, orders and
          documents in one place.
        </p>
        <div className={s.brandFoot}>Government of Assam · For authorised officers only</div>
      </aside>
      <main className={s.panel}>{children}</main>
    </div>
  );
}
