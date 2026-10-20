/**
 * The language seams (design portal-ui-redesign, decision 27). English only now: every user-facing string lives in
 * `messages.ts`, and a second catalogue would be a static file produced offline and reviewed by people. The portal
 * never calls a translation service at run time, and no provider interface or credential exists here.
 */
import { T, type Messages } from "./messages";

export interface LocaleInfo {
  /** The catalogue's code. */
  code: string;
  /** `<html lang>`. */
  htmlLang: string;
  /** The `Intl` locale used for dates and numbers in any language other than English. */
  intl: string;
  /** `<html dir>`. */
  dir: "ltr" | "rtl";
}

export const LOCALES = {
  en: { code: "en", htmlLang: "en", intl: "en-IN", dir: "ltr" },
} as const satisfies Record<string, LocaleInfo>;

export type LocaleCode = keyof typeof LOCALES;

export const DEFAULT_LOCALE: LocaleCode = "en";

/** The catalogues by locale; each must have the English keys and function arities (i18n.test.ts checks). */
export const CATALOGUES: Record<LocaleCode, Messages> = {
  en: T,
};

/** A locale's catalogue; an unknown code gets English. */
export function messagesFor(code: string): Messages {
  return (CATALOGUES as Record<string, Messages>)[code] ?? CATALOGUES[DEFAULT_LOCALE];
}

/** A locale by code or as given; anything unknown is English. */
export function localeOf(locale?: string | LocaleInfo | null): LocaleInfo {
  if (locale && typeof locale === "object") return locale;
  if (typeof locale === "string" && locale in LOCALES) return LOCALES[locale as LocaleCode];
  return LOCALES[DEFAULT_LOCALE];
}

/** The `lang` and `dir` of the page's `<html>` element. */
export function htmlAttributes(locale?: string | LocaleInfo | null): { lang: string; dir: "ltr" | "rtl" } {
  const l = localeOf(locale);
  return { lang: l.htmlLang, dir: l.dir };
}
