/**
 * The Government of Assam branding (design portal-ui-redesign, decision 21). No emblem is drawn, traced or
 * approximated anywhere in the code: the images are the official files the owner supplied (20 Oct 2026), kept
 * unaltered in `frontend/public/brand/`. `emblem` is the lion capital cut from the official file for the 40 px header
 * slot; `lockup` is the whole official emblem with its legends, for the public pages. To replace them, the owner
 * places new files there, updates the sizes below, and the `web` image is rebuilt.
 */
export interface EmblemImage {
  /** The path under `public/`, for example `/brand/assam-emblem.svg`. */
  src: string;
  width: number;
  height: number;
}

export interface BrandConfig {
  emblem: EmblemImage | null;
  lockup?: EmblemImage | null;
}

export const BRAND: BrandConfig = {
  emblem: { src: "/brand/assam-emblem-mark.png", width: 392, height: 506 },
  lockup: { src: "/brand/assam-emblem-lockup.png", width: 350, height: 365 },
};
