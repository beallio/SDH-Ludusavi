import { ButtonItem, Spinner } from "@decky/ui";
import type { ReactNode } from "react";

type SpinnerButtonProps = {
  children: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  [key: string]: unknown;
};

export function SpinnerButton({ children, loading, ...props }: SpinnerButtonProps) {
  return (
    <ButtonItem {...props} disabled={Boolean(props.disabled) || loading}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
        {loading && <Spinner style={{ width: "18px", height: "18px", color: "#1a9fff" }} />}
        {children}
      </div>
    </ButtonItem>
  );
}
