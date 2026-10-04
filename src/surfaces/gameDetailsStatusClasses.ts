import { basicAppDetailsSectionStylerClasses, playSectionClasses } from "@decky/ui";

export type NativeGameDetailsStatusClasses = Readonly<{
  row: string;
  icon: string;
  iconSvg: string;
  label: string;
  problem: string;
  syncing: string;
  activeValue: string;
  appDetailsRoot: string | null;
  playSection: string;
}>;

let cachedClasses: NativeGameDetailsStatusClasses | null = null;

export function getNativeGameDetailsStatusClasses(): NativeGameDetailsStatusClasses | null {
  const play = playSectionClasses as Record<string, string | undefined> | undefined;
  const root = basicAppDetailsSectionStylerClasses as Record<string, string | undefined> | undefined;
  const row = play?.CloudStatusRow;
  const icon = play?.CloudStatusIcon;
  const iconSvg = play?.CloudIconSVG;
  const label = play?.CloudStatusLabel;
  const problem = play?.CloudSyncProblem;
  const syncing = play?.CloudSynching;
  const activeValue = play?.CloudStatusUploading;
  const appDetailsRoot = root?.AppDetailsRoot;
  const playSection = root?.PlaySection;
  if (typeof row !== "string" || !row || typeof icon !== "string" || !icon
    || typeof iconSvg !== "string" || !iconSvg || typeof label !== "string" || !label
    || typeof problem !== "string" || !problem || typeof syncing !== "string" || !syncing
    || typeof activeValue !== "string" || !activeValue || typeof playSection !== "string" || !playSection) return null;
  if (cachedClasses?.row === row && cachedClasses.icon === icon && cachedClasses.iconSvg === iconSvg
    && cachedClasses.label === label && cachedClasses.problem === problem && cachedClasses.syncing === syncing
    && cachedClasses.activeValue === activeValue
    && cachedClasses.appDetailsRoot === (typeof appDetailsRoot === "string" ? appDetailsRoot : null)
    && cachedClasses.playSection === playSection) return cachedClasses;
  cachedClasses = {
    row, icon, iconSvg, label, problem, syncing, activeValue,
    appDetailsRoot: typeof appDetailsRoot === "string" ? appDetailsRoot : null,
    playSection,
  };
  return cachedClasses;
}
