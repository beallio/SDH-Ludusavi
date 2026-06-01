import { ButtonItem, ConfirmModal } from "@decky/ui";

import { formatConflictTime } from "../../formatting/dateTime";
import type { ConflictResolution, LifecycleCheckResult } from "../../types";

type ConflictResolutionModalProps = {
  conflict: LifecycleCheckResult;
  onChoose: (resolution: ConflictResolution) => void;
  onDismiss: () => void;
  closeModal?: () => void;
};

export function ConflictResolutionModal({
  conflict,
  onChoose,
  onDismiss,
  closeModal
}: ConflictResolutionModalProps) {
  const choose = (resolution: ConflictResolution) => {
    closeModal?.();
    onChoose(resolution);
  };
  const dismiss = () => {
    closeModal?.();
    onDismiss();
  };
  return (
    <ConfirmModal
      bAlertDialog={true}
      strTitle="Conflict Detected"
      onOK={dismiss}
      onCancel={dismiss}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px" }}>
        <div>
          Both your local save and backup save appear to have changed. Choose which version
          should be used before the game continues loading.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <div>Keep Local Save: {formatConflictTime(conflict.localModifiedAt)}</div>
          <div>Restore Backup Save: {formatConflictTime(conflict.backupModifiedAt)}</div>
          {conflict.backupPath && <div>Backup path: {conflict.backupPath}</div>}
        </div>
        <ButtonItem layout="below" onClick={() => choose("keep_local")}>
          Keep Local Save
        </ButtonItem>
        <ButtonItem layout="below" onClick={() => choose("restore_backup")}>
          Restore Backup Save
        </ButtonItem>
      </div>
    </ConfirmModal>
  );
}
