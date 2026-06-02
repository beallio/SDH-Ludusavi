type QamStylesProps = {
  cssText: string | null;
};

export function QamStyles({ cssText }: QamStylesProps) {
  return <style>{cssText}</style>;
}
