import { FC } from "react";
import { ModalRoot, DialogButton, showModal } from "@decky/ui";
import { resolveNewerInSlot, logError } from "../api/backend";
import type { NewerInSlotConflict } from "../types";
import { formatTimestamp } from "../utils/formatters";

export type NewerInSlotResolution = "use_newer" | "keep_current" | "dismiss" | "cancel";

interface NewerInSlotModalProps {
  conflict: NewerInSlotConflict;
  closeModal?: () => void;
  onDone: (resolution: NewerInSlotResolution) => void;
}

const NewerInSlotModalContent: FC<NewerInSlotModalProps> = ({ conflict, closeModal, onDone }) => {
  const slotLabel = conflict.slot ? `'${conflict.slot}'` : "the default slot";

  const handleChoice = async (resolution: NewerInSlotResolution) => {
    if (resolution === "cancel") {
      closeModal?.();
      onDone("cancel");
      return;
    }

    try {
      await resolveNewerInSlot(
        conflict.rom_id,
        conflict.filename,
        resolution,
        conflict.newer_save_id,
      );
    } catch (e) {
      logError(`Failed to resolve newer-in-slot conflict (${resolution}): ${e}`);
      closeModal?.();
      onDone("cancel");
      return;
    }

    closeModal?.();
    onDone(resolution);
  };

  return (
    <ModalRoot closeModal={() => { closeModal?.(); onDone("cancel"); }}>
      <div style={{ padding: "16px", minWidth: "320px" }}>
        <div style={{
          fontSize: "16px",
          fontWeight: "bold",
          marginBottom: "4px",
          color: "#fff",
        }}>
          Newer Save Detected
        </div>
        <div style={{
          fontSize: "13px",
          color: "rgba(255, 255, 255, 0.6)",
          marginBottom: "16px",
        }}>
          {conflict.filename}
        </div>

        <div style={{
          fontSize: "13px",
          color: "rgba(255, 255, 255, 0.85)",
          marginBottom: "12px",
          lineHeight: "1.5",
        }}>
          Another device uploaded a newer save to slot {slotLabel} on{" "}
          <strong>{formatTimestamp(conflict.newer_updated_at)}</strong>. Your plugin is currently
          tracking an older save{conflict.tracked_updated_at
            ? <> (from <strong>{formatTimestamp(conflict.tracked_updated_at)}</strong>)</>
            : " (no tracked save)"
          }.
        </div>

        <div style={{
          fontSize: "12px",
          color: "rgba(255, 255, 255, 0.55)",
          marginBottom: "20px",
          lineHeight: "1.5",
          padding: "10px",
          background: "rgba(255, 255, 255, 0.05)",
          borderRadius: "4px",
          border: "1px solid rgba(255, 255, 255, 0.1)",
        }}>
          This usually happens when another device uses a different save sync client (like Argosy
          or the RomM web UI). These tools may create separate save entries instead of updating
          yours.
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "16px" }}>
          <DialogButton onClick={() => handleChoice("use_newer")}>
            Use the newer save
          </DialogButton>
          <DialogButton onClick={() => handleChoice("keep_current")}>
            Keep my current save
          </DialogButton>
          <DialogButton
            onClick={() => handleChoice("dismiss")}
            style={{ opacity: 0.8 }}
          >
            Keep my current save and stop asking
          </DialogButton>
          <DialogButton
            onClick={() => handleChoice("cancel")}
            style={{ opacity: 0.5 }}
          >
            Cancel
          </DialogButton>
        </div>

        <div style={{
          fontSize: "11px",
          color: "rgba(255, 255, 255, 0.4)",
          lineHeight: "1.5",
        }}>
          To avoid this in the future, change the default slot on the other device or sync client
          to a unique name. If that's not possible, change the slot used in this plugin's settings
          so each client uses its own slot.
        </div>
      </div>
    </ModalRoot>
  );
};

/**
 * Show the newer-in-slot conflict modal and return a Promise that resolves
 * when the user picks an option.
 */
export function showNewerInSlotModal(
  conflict: NewerInSlotConflict,
): Promise<NewerInSlotResolution> {
  return new Promise<NewerInSlotResolution>((resolve) => {
    showModal(
      <NewerInSlotModalContent
        conflict={conflict}
        onDone={resolve}
      />,
    );
  });
}
