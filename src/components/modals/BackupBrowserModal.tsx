import { useEffect, useRef, useState } from "react";
import {
  ConfirmModal,
  DialogBody,
  DialogBodyText,
  DialogButton,
  DialogHeader,
  Field,
  ModalRoot,
  showModal,
} from "@decky/ui";
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
  const firstRowRef = useRef<HTMLDivElement | null>(null);

  // Gamepad focus lands on the footer Close button when the modal mounts,
  // dragging the list to the bottom; reset to the top once content settles.
  useEffect(() => {
    if (loading || error) {
      scrollRef.current?.scrollTo({ top: 0 });
      return;
    }
    if (!listResult?.backups.length) {
      scrollRef.current?.scrollTo({ top: 0 });
      return;
    }
    const id = requestAnimationFrame(() =>
      requestAnimationFrame(() => firstRowRef.current?.focus())
    );
    return () => cancelAnimationFrame(id);
  }, [loading, error, listResult]);

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
      <DialogHeader>Backups: {gameName}</DialogHeader>
      <DialogBody ref={scrollRef}>
        {loading && <DialogBodyText>Loading backups...</DialogBodyText>}
        {error && <DialogBodyText style={{ color: "red" }}>Error: {error}</DialogBodyText>}
        {!loading && !error && listResult && (
          <>
            <DialogBodyText>
              <strong>Path:</strong> {listResult.backup_path || "Unknown"}
              <br />
              <strong>Total Size:</strong>{" "}
              {listResult.total_size_bytes !== null
                ? formatBytes(listResult.total_size_bytes)
                : "Unknown"}{" "}
              ({listResult.backups.length} snapshots)
            </DialogBodyText>
            {listResult.backups.length === 0 ? (
              <DialogBodyText>No backups found.</DialogBodyText>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "10px" }}>
                {listResult.backups.map((b, idx) => {
                  const timestampStr = formatTimestamp(b.when);
                  const title = `${timestampStr}${b.locked ? " (Locked)" : ""}`;
                  const sizeText =
                    `${b.file_count !== null ? `${b.file_count} files ` : ""}` +
                    `${b.size_bytes !== null ? formatBytes(b.size_bytes) : ""}`.trim();
                  const description = (
                    <>
                      {sizeText}
                      {b.comment && (<><br />Comment: {b.comment}</>)}
                    </>
                  );

                  return (
                    <Field
                      key={b.id}
                      label={title}
                      description={description}
                      bottomSeparator="standard"
                    >
                      <DialogButton
                        ref={idx === 0 ? firstRowRef : undefined}
                        preferredFocus={idx === 0}
                        onClick={() => onRestore(b.id, timestampStr)}
                      >
                        Restore
                      </DialogButton>
                    </Field>
                  );
                })}
              </div>
            )}
          </>
        )}
      </DialogBody>
    </ModalRoot>
  );
}
