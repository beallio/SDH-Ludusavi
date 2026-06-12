import { useEffect, useState } from "react";
import { ButtonItem, ConfirmModal, ModalRoot, showModal } from "@decky/ui";
import { formatBytes } from "../../formatting/bytes";
import { formatTimestamp } from "../../formatting/dateTime";
import type { BackupListResult, OperationResult } from "../../types";
import { listBackupsCall, restoreBackupVersionCall } from "../../api/ludusaviRpc";

type BackupBrowserModalProps = {
  gameName: string;
  closeModal?: () => void;
  onRestoreComplete?: (result: OperationResult) => void;
  isRpcStatus: (res: any) => boolean;
  logRpcStatus: (res: any, op: string) => void;
};

export function BackupBrowserModal({
  gameName,
  closeModal,
  onRestoreComplete,
  isRpcStatus,
  logRpcStatus,
}: BackupBrowserModalProps) {
  const [loading, setLoading] = useState(true);
  const [listResult, setListResult] = useState<BackupListResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchBackups = async () => {
      try {
        const res = await listBackupsCall(gameName);
        if (!mounted) return;
        if (isRpcStatus(res)) {
          logRpcStatus(res, "list_backups");
          setError((res as any).message || "Failed to list backups");
        } else {
          setListResult(res as BackupListResult);
        }
      } catch (e: any) {
        if (!mounted) return;
        setError(e.toString());
      } finally {
        if (mounted) setLoading(false);
      }
    };
    fetchBackups();
    return () => {
      mounted = false;
    };
  }, [gameName, isRpcStatus, logRpcStatus]);

  const onRestore = async (backupId: string) => {
    showModal(
      <ConfirmModal
        strTitle="Confirm Restore"
        strDescription={`Are you sure you want to restore backup ${backupId} for ${gameName}? This will overwrite your current save data.`}
        bAlertDialog={false}
        onOK={async () => {
          setLoading(true);
          try {
            const res = await restoreBackupVersionCall(gameName, backupId);
            if (isRpcStatus(res)) {
              logRpcStatus(res, "restore_backup_version");
              setError((res as any).message || "Failed to restore backup");
            } else {
              closeModal?.();
              onRestoreComplete?.(res as OperationResult);
            }
          } catch (e: any) {
            setError(e.toString());
          } finally {
            setLoading(false);
          }
        }}
      />
    );
  };

  return (
    <ModalRoot onCancel={closeModal} bHideBuiltInClose={false}>
      <div style={{ display: "flex", flexDirection: "column", height: "100%", width: "100%", background: "#212224" }}>
        <div style={{ padding: "16px", borderBottom: "1px solid #333", fontSize: "1.2em" }}>
          Backups: {gameName}
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "10px" }}>
          {loading && <div>Loading backups...</div>}
          {error && <div style={{ color: "red" }}>Error: {error}</div>}
          {!loading && !error && listResult && (
            <>
              <div>
                <strong>Path:</strong> {listResult.backup_path || "Unknown"}
                <br />
                <strong>Total Size:</strong>{" "}
                {listResult.total_size_bytes !== null
                  ? formatBytes(listResult.total_size_bytes)
                  : "Unknown"}
              </div>
              {listResult.backups.length === 0 ? (
                <div>No backups found.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "10px" }}>
                  {listResult.backups.map((b) => (
                    <div
                      key={b.id}
                      style={{
                        padding: "12px",
                        backgroundColor: "rgba(255, 255, 255, 0.05)",
                        borderRadius: "8px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                        <div>
                          <strong>{formatTimestamp(b.when)}</strong> {b.locked ? "(Locked)" : ""}
                        </div>
                        <div style={{ fontSize: "14px", opacity: 0.8 }}>
                          {b.size_bytes !== null ? formatBytes(b.size_bytes) : ""}
                        </div>
                      </div>
                      {b.comment && (
                        <div style={{ fontSize: "14px", marginBottom: "8px" }}>
                          Comment: {b.comment}
                        </div>
                      )}
                      <div style={{ display: "flex", justifyContent: "flex-end" }}>
                        <ButtonItem layout="below" onClick={() => onRestore(b.id)}>
                          Restore
                        </ButtonItem>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div style={{ padding: "16px", borderTop: "1px solid #333", display: "flex", justifyContent: "flex-end" }}>
          <ButtonItem layout="below" onClick={closeModal}>
            Close
          </ButtonItem>
        </div>
      </div>
    </ModalRoot>
  );
}
