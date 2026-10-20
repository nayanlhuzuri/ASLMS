/**
 * The Government of Assam branding (design portal-ui-redesign, decision 21). No emblem is drawn, traced or
 * approximated anywhere in the code: until the owner supplies the official file, the header shows a marked
 * placeholder. To install it, the owner places the official file in `frontend/public/brand/` (SVG, or PNG at least
 * 160 px high), sets `emblem` below, and the `web` image is rebuilt.
 */
export interface EmblemImage {
  /** The path under `public/`, for example `/brand/assam-emblem.svg`. */
  src: string;
  width: number;
  height: number;
}

export interface BrandConfig {
  emblem: EmblemImage | null;
}

export const BRAND: BrandConfig = {
  emblem: null,
};
