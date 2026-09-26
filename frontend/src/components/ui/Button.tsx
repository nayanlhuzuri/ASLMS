import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import s from "./ui.module.css";

export type Variant = "primary" | "secondary" | "danger" | "link";

function classes(variant: Variant, small?: boolean, extra?: string) {
  return [s.btn, s[variant], small ? s.small : "", extra ?? ""].filter(Boolean).join(" ");
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  small?: boolean;
  icon?: IconName;
  busy?: boolean;
}

export function Button({ variant = "secondary", small, icon, busy, children, className, disabled, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={classes(variant, small, className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className={s.spinner} aria-hidden="true" /> : icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </button>
  );
}

interface LinkButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
  variant?: Variant;
  small?: boolean;
  icon?: IconName;
  children: ReactNode;
  /** Plain <a> (downloads, API links, new tabs) instead of client-side navigation. */
  external?: boolean;
}

export function LinkButton({ href, variant = "secondary", small, icon, children, className, external, ...rest }: LinkButtonProps) {
  const cls = classes(variant, small, className);
  const inner = (
    <>
      {icon ? <Icon name={icon} size={16} /> : null}
      {children}
    </>
  );
  if (external) {
    return (
      <a href={href} className={cls} {...rest}>
        {inner}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} {...rest}>
      {inner}
    </Link>
  );
}

export function IconButton({
  icon,
  label,
  className,
  ...rest
}: { icon: IconName; label: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" aria-label={label} title={label} className={[s.iconButton, className ?? ""].join(" ")} {...rest}>
      <Icon name={icon} />
    </button>
  );
}
