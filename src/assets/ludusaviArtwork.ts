import gridP from "../../assets/steamgrid/ludusavi/grid_p.png";
import gridL from "../../assets/steamgrid/ludusavi/grid_l.png";
import hero from "../../assets/steamgrid/ludusavi/hero.png";

// Artwork source: SteamGridDB game 5360951, downloaded at build/development time.
// Runtime code must use these bundled local files only.
export const LUDUSAVI_ARTWORK = {
  grid_p: gridP,
  grid_l: gridL,
  hero,
} as const;

export type LudusaviArtworkAsset = keyof typeof LUDUSAVI_ARTWORK;
