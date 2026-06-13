import { useEffect, useRef, useState } from "react";
import { ButtonItem, ConfirmModal, Focusable, ModalRoot, showModal } from "@decky/ui";
import { formatBytes } from "../../formatting/bytes";
import { formatTimestamp } from "../../formatting/dateTime";
import type { BackupListResult } from "../../types";
import { listBackupsCall } from "../../api/ludusaviRpc";

type BackupBrowserModalProps = {
  gameName: string;
  closeModal?: () => void;
  onRestoreSnapshot?: (backupId: string, whenLabel: string) => void;
  isRpcStatus: (res: any) => boolean;
  logRpcStatus: (res: any, op: string) => void;
};

export function BackupBrowserModal({
  gameName,
  closeModal,
  onRestoreSnapshot,
  isRpcStatus,
  logRpcStatus,
}: BackupBrowserModalProps) {
  const [loading, setLoading] = useState(true);
  const [listResult, setListResult] = useState<BackupListResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Gamepad focus lands on the footer Close button when the modal mounts,
  // dragging the list to the bottom; reset to the top once content settles.
  useEffect(() => {
    if (!loading) scrollRef.current?.scrollTo({ top: 0 });
  }, [loading]);

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

  const onRestore = (backupId: string, whenLabel: string) => {
    showModal(
      <ConfirmModal
        strTitle="Confirm Restore"
        strDescription={`Are you sure you want to restore ${gameName} to the backup from ${whenLabel}? This will overwrite your current save data.`}
        bAlertDialog={false}
        onOK={() => {
          closeModal?.();
          onRestoreSnapshot?.(backupId, whenLabel);
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
        <div
          ref={scrollRef}
          style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "10px" }}
        >
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
                  : "Unknown"}{" "}
                ({listResult.backups.length} snapshots)
              </div>
              {listResult.backups.length === 0 ? (
                <div>No backups found.</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "10px" }}>
                  {listResult.backups.map((b, idx) => (
                    <div
                      key={b.id}
                      style={{
                        padding: "12px",
                        // Matches the Steam DialogButton fill so cards and
                        // their Restore buttons read as one surface.
                        backgroundColor: "#43464c",
                        borderRadius: "8px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px" }}>
                        <div>
                          <strong>{formatTimestamp(b.when)}</strong> {b.locked ? "(Locked)" : ""}
                        </div>
                        <div style={{ fontSize: "14px", opacity: 0.8 }}>
                          {b.file_count !== null ? `${b.file_count} files ` : ""}
                          {b.size_bytes !== null ? formatBytes(b.size_bytes) : ""}
                        </div>
                      </div>
                      {b.comment && (
                        <div style={{ fontSize: "14px", marginBottom: "8px" }}>
                          Comment: {b.comment}
                        </div>
                      )}
                      <Focusable
                        style={{ display: "flex", justifyContent: "flex-end" }}
                        preferredFocus={idx === 0}
                        noFocusRing={true}
                      >
                        <ButtonItem layout="below" onClick={() => onRestore(b.id, formatTimestamp(b.when))}>
                          Restore
                        </ButtonItem>
                      </Focusable>
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
