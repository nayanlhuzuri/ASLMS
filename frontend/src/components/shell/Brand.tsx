/**
 * The emblem slot and the brand text (design portal-ui-redesign, decision 21). No emblem is drawn here: with
 * `BRAND.emblem` null the slot is a marked placeholder hidden from screen readers; with a file set it is the
 * official image with its alternative text. The same slot appears in the header, the drawer's top and (round 5) the
 * public pages.
 */
import type { BrandConfig } from "@/lib/brand";
import { BRAND } from "@/lib/brand";
import { T } from "@/lib/messages";

import s from "./shell.module.css";

export function EmblemSlot({ brand = BRAND }: { brand?: BrandConfig }) {
  const emblem = brand.emblem;
  if (emblem) {
    // a plain <img>: the official file is a static asset of the portal, shown at 40 px high
    // eslint-disable-next-line @next/next/no-img-element
    return <img className={s.emblemImage} src={emblem.src} width={Math.round((emblem.width * 40) / emblem.height)} height={40} alt={T.brand.emblemAlt} />;
  }
  return (
    <span className={s.emblem} title={T.brand.emblemTitle} aria-hidden="true">
      {T.brand.emblemPlaceholder}
    </span>
  );
}

export function Brand({ brand = BRAND }: { brand?: BrandConfig }) {
  return (
    <div className={s.brand}>
      <EmblemSlot brand={brand} />
      <span className={s.brandText}>
        <span className={s.gov}>{T.owner}</span>
        <span className={s.app}>{T.portalLong}</span>
      </span>
    </div>
  );
}
