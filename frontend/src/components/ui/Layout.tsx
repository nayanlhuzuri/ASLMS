import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import s from "./ui.module.css";

export function Card({
  children,
  className,
  style,
  as: Tag = "section",
  labelledBy,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "section" | "div" | "article";
  labelledBy?: string;
}) {
  return (
    <Tag className={[s.card, className ?? ""].join(" ")} style={style} aria-labelledby={labelledBy}>
      {children}
    </Tag>
  );
}

export function CardHead({ title, id, caption, actions }: { title?: ReactNode; id?: string; caption?: boolean; actions?: ReactNode }) {
  return (
    <div className={s.cardHead}>
      {caption ? (
        <h2 id={id} className={s.caption} style={{ fontFamily: "var(--font-sans)" }}>
          {title}
        </h2>
      ) : (
        <h2 id={id}>{title}</h2>
      )}
      {actions}
    </div>
  );
}

export function Caption({ children }: { children: ReactNode }) {
  return <div className={s.caption}>{children}</div>;
}

export function PageHeader({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className={s.pageHeader}>
      <div className={s.pageTitle}>
        <h1>{title}</h1>
        {sub ? <div className={s.pageSub}>{sub}</div> : null}
      </div>
      {actions ? <div className={`${s.pageActions} no-print`}>{actions}</div> : null}
    </div>
  );
}

export function KV({ items }: { items: { label: string; value: ReactNode; mono?: boolean }[] }) {
  return (
    <dl className={s.kv} style={{ margin: 0 }}>
      {items.map((it) => (
        <div key={it.label} className={s.kvItem}>
          <dt className={s.kvLabel}>{it.label}</dt>
          <dd className={`${s.kvValue} ${it.mono ? "mono" : ""}`} style={{ margin: 0 }}>
            {it.value ?? "-"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warning" }) {
  return <div className={`${s.notice} ${tone === "warning" ? s.noticeWarning : ""}`}>{children}</div>;
}

export function Kpi({
  label,
  value,
  note,
  tone,
  href,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "accent" | "critical" | "warning";
  href?: string;
}) {
  const toneClass = tone === "accent" ? s.kpiAccent : tone === "critical" ? s.kpiCritical : tone === "warning" ? s.kpiWarning : "";
  const body = (
    <>
      <div className={s.caption}>{label}</div>
      <div className={`${s.kpiValue} ${toneClass}`}>{value}</div>
      {note ? <div className={s.kpiNote}>{note}</div> : null}
    </>
  );
  if (href) {
    return (
      <Link href={href} className={s.kpi}>
        {body}
      </Link>
    );
  }
  return <div className={s.kpi}>{body}</div>;
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className={s.kpiRow}>{children}</div>;
}
