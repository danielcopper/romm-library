import { useState, useEffect, FC } from "react";
import { DialogButton } from "@decky/ui";
import { getSaveSetupInfo, confirmSlotChoice, logError } from "../api/backend";
import type { SaveSetupInfo } from "../types";

interface SlotSetupWizardProps {
  romId: number;
  onComplete: () => void;
}

function displaySlot(slot: string | null): string {
  if (slot === null || slot === "") return "(no slot)";
  return slot;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "unknown";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export const SlotSetupWizard: FC<SlotSetupWizardProps> = ({ romId, onComplete }) => {
  const [info, setInfo] = useState<SaveSetupInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [customSlot, setCustomSlot] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchInfo = async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await getSaveSetupInfo(romId);
        if (cancelled) return;

        // Scenario B: local saves, no server saves — auto-confirm with default slot
        if (result.has_local_saves && result.server_slots.length === 0) {
          setConfirming(true);
          try {
            await confirmSlotChoice(romId, result.default_slot, null);
            if (!cancelled) onComplete();
          } catch (e) {
            if (!cancelled) {
              setError(`Auto-setup failed: ${e}`);
              logError(`SlotSetupWizard auto-confirm failed: ${e}`);
              setConfirming(false);
              setInfo(result);
            }
          }
          if (!cancelled) setLoading(false);
          return;
        }

        setInfo(result);
      } catch (e) {
        if (!cancelled) {
          setError(`Failed to load save setup info: ${e}`);
          logError(`SlotSetupWizard fetch failed: ${e}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchInfo();
    return () => { cancelled = true; };
  }, [romId]);

  const handleConfirm = async (slot: string, migrateFrom?: string | null) => {
    setConfirming(true);
    setError(null);
    try {
      const result = await confirmSlotChoice(romId, slot, migrateFrom ?? null);
      if (!result.success) {
        setError(result.message || "Slot confirmation failed");
        setConfirming(false);
        return;
      }
      onComplete();
    } catch (e) {
      setError(`Failed to confirm slot: ${e}`);
      logError(`SlotSetupWizard confirm failed: ${e}`);
      setConfirming(false);
    }
  };

  // Loading state
  if (loading || (confirming && !error)) {
    return (
      <div className="romm-panel-section">
        <div className="romm-panel-section-title">Save Slot Setup</div>
        <div className="romm-panel-muted">
          {confirming ? "Setting up..." : "Loading save information..."}
        </div>
      </div>
    );
  }

  // Error state with retry
  if (error && !info) {
    return (
      <div className="romm-panel-section">
        <div className="romm-panel-section-title">Save Slot Setup</div>
        <div style={{ color: "#d4513f", fontSize: "12px", marginBottom: "8px" }}>{error}</div>
        <DialogButton
          onClick={() => {
            setError(null);
            setLoading(true);
            getSaveSetupInfo(romId).then(
              (result) => { setInfo(result); setLoading(false); },
              (e) => { setError(`Failed to load: ${e}`); setLoading(false); },
            );
          }}
        >
          Retry
        </DialogButton>
      </div>
    );
  }

  if (!info) return null;

  const hasLocalSaves = info.has_local_saves;
  const hasServerSlots = info.server_slots.length > 0;
  const defaultSlot = info.default_slot;

  // Check if server has saves in the default slot
  const serverHasDefaultSlot = info.server_slots.some((s) => s.slot === defaultSlot);

  // Determine scenario
  const renderScenario = () => {
    // Scenario A: No local saves, server has saves
    if (!hasLocalSaves && hasServerSlots) {
      return renderScenarioA();
    }

    // Scenario C: Local saves, server has saves in non-default slot(s)
    if (hasLocalSaves && hasServerSlots && !serverHasDefaultSlot) {
      return renderScenarioC();
    }

    // Scenario E: Local saves, server has saves in the default slot
    if (hasLocalSaves && hasServerSlots && serverHasDefaultSlot) {
      return renderScenarioE();
    }

    // Fallback: no local, no server — just start fresh
    return renderFallback();
  };

  const renderSlotList = (slots: SaveSetupInfo["server_slots"]) => (
    <div style={{ marginBottom: "8px" }}>
      {slots.map((s) => (
        <div
          key={s.slot ?? "__null__"}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "6px 0",
            borderBottom: "1px solid rgba(255,255,255,0.1)",
          }}
        >
          <div>
            <div style={{ fontSize: "13px", color: "#fff" }}>
              <span className="romm-status-dot" style={{ backgroundColor: "#1a9fff" }} />
              {displaySlot(s.slot)}
            </div>
            <div className="romm-panel-muted" style={{ fontSize: "11px" }}>
              {s.count} file{s.count !== 1 ? "s" : ""}
              {s.latest_updated_at && ` \u2014 updated ${formatTimestamp(s.latest_updated_at)}`}
            </div>
          </div>
          <DialogButton
            style={{ minWidth: "auto", padding: "4px 12px", fontSize: "12px" }}
            disabled={confirming}
            onClick={() => handleConfirm(s.slot ?? defaultSlot, s.slot === null ? null : undefined)}
          >
            Track This Slot
          </DialogButton>
        </div>
      ))}
    </div>
  );

  const renderCustomSlotInput = () => (
    <div style={{ display: "flex", gap: "8px", alignItems: "center", marginTop: "8px" }}>
      <input
        type="text"
        placeholder="Custom slot name"
        value={customSlot}
        onChange={(e) => setCustomSlot(e.target.value)}
        style={{
          flex: 1,
          padding: "6px 8px",
          fontSize: "12px",
          background: "rgba(255,255,255,0.1)",
          border: "1px solid rgba(255,255,255,0.2)",
          borderRadius: "4px",
          color: "#fff",
          outline: "none",
        }}
      />
      <DialogButton
        style={{ minWidth: "auto", padding: "4px 12px", fontSize: "12px" }}
        disabled={confirming || !customSlot.trim()}
        onClick={() => handleConfirm(customSlot.trim())}
      >
        Use Custom
      </DialogButton>
    </div>
  );

  const renderLocalFiles = () => {
    if (!info.local_files.length) return null;
    return (
      <div style={{ marginBottom: "8px" }}>
        <div className="romm-panel-muted" style={{ fontSize: "11px", marginBottom: "4px" }}>
          Local saves:
        </div>
        {info.local_files.map((f) => (
          <div key={f.filename} className="romm-panel-info-row" style={{ fontSize: "12px" }}>
            <span>{f.filename}</span>
            <span className="romm-panel-muted">{formatSize(f.size)}</span>
          </div>
        ))}
      </div>
    );
  };

  // Scenario A: No local saves, server has saves
  const renderScenarioA = () => (
    <div>
      <div className="romm-panel-muted" style={{ marginBottom: "8px" }}>
        Server has saves in these slots:
      </div>
      {renderSlotList(info.server_slots)}
      <div style={{ marginTop: "8px" }}>
        <DialogButton
          style={{ fontSize: "12px" }}
          disabled={confirming}
          onClick={() => handleConfirm(defaultSlot)}
        >
          Start fresh with slot '{defaultSlot}'
        </DialogButton>
      </div>
      {renderCustomSlotInput()}
    </div>
  );

  // Scenario C: Local saves, server has saves in non-default slot(s)
  const renderScenarioC = () => (
    <div>
      <div className="romm-panel-muted" style={{ marginBottom: "8px" }}>
        You have local saves and the server has saves too.
      </div>
      {renderLocalFiles()}
      <div className="romm-panel-muted" style={{ fontSize: "11px", marginBottom: "4px" }}>
        Server slots:
      </div>
      {renderSlotList(info.server_slots)}
      <div style={{ marginTop: "8px" }}>
        <DialogButton
          style={{ fontSize: "12px" }}
          disabled={confirming}
          onClick={() => handleConfirm(defaultSlot)}
        >
          Upload to slot '{defaultSlot}'
        </DialogButton>
      </div>
      {renderCustomSlotInput()}
    </div>
  );

  // Scenario E: Local saves, server has saves in the default slot
  const renderScenarioE = () => (
    <div>
      <div className="romm-panel-muted" style={{ marginBottom: "8px" }}>
        Server already has saves in your default slot '{defaultSlot}'.
      </div>
      {renderLocalFiles()}
      <div style={{ marginTop: "8px" }}>
        <DialogButton
          style={{ fontSize: "12px", marginBottom: "8px" }}
          disabled={confirming}
          onClick={() => handleConfirm(defaultSlot)}
        >
          Track this slot
        </DialogButton>
      </div>
      <div className="romm-panel-muted" style={{ fontSize: "11px", marginBottom: "4px" }}>
        Or use a different slot:
      </div>
      {renderCustomSlotInput()}
    </div>
  );

  // Fallback: no saves anywhere
  const renderFallback = () => (
    <div>
      <div className="romm-panel-muted" style={{ marginBottom: "8px" }}>
        No existing saves found. Start tracking with the default slot.
      </div>
      <DialogButton
        style={{ fontSize: "12px" }}
        disabled={confirming}
        onClick={() => handleConfirm(defaultSlot)}
      >
        Use slot '{defaultSlot}'
      </DialogButton>
      {renderCustomSlotInput()}
    </div>
  );

  return (
    <div className="romm-panel-section">
      <div className="romm-panel-section-title">Save Slot Setup</div>
      {error && (
        <div style={{ color: "#d4513f", fontSize: "12px", marginBottom: "8px" }}>{error}</div>
      )}
      {renderScenario()}
    </div>
  );
};
