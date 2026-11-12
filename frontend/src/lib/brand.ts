/**
 * The Government of Assam branding (design portal-ui-redesign, decision 21, as amended by design signin-gold-emblem,
 * row 249). No emblem is drawn, traced or approximated anywhere in the code: the images are the official files the
 * owner supplied, kept unaltered in `frontend/public/brand/`. `emblem` is the lion capital cut from the official file
 * (20 Oct 2026) for the 40 px header slot. `capital` is the Lion Capital cut-out the owner supplied with row 249
 * (12 Nov 2026), copied byte for byte from `docs/design/ui/assam-emblem-capital-mask.png`; the sign-in frame uses it as
 * a CSS mask over the gold gradient, which the owner allowed (point 2). To replace them, the owner places new files
 * there, updates the sizes below, and the `web` image is rebuilt.
 */
export interface EmblemImage {
  /** The path under `public/`, for example `/brand/assam-emblem.svg`. */
  src: string;
  width: number;
  height: number;
}

export interface BrandConfig {
  emblem: EmblemImage | null;
  capital?: EmblemImage | null;
}

export const BRAND: BrandConfig = {
  emblem: { src: "/brand/assam-emblem-mark.png", width: 392, height: 506 },
  capital: { src: "/brand/assam-emblem-capital-mask.png", width: 508, height: 756 },
};
