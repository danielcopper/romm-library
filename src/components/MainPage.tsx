import { useState, useEffect, useRef, FC } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  ProgressBarWithInfo,
  DropdownItem,
  ToggleField,
  Spinner,
} from "@decky/ui";
import {
  testConnection,
  cancelSync,
  getSyncStats,
  getSettings,
  saveLogLevel,
  fixRetroarchInputDriver,
  syncPreview,
  syncApplyDelta,
  syncCancelPreview,
} from "../api/backend";
import { getSyncProgress } from "../utils/syncProgress";
import { getMigrationState, onMigrationChange } from "../utils/migrationStore";
import { requestSyncCancel } from "../utils/syncManager";
import type { SyncProgress, SyncStats, SyncPreview } from "../types";
import type { MigrationStatus } from "../api/backend";

type Page = "connection" | "platforms" | "danger" | "downloads" | "bios" | "savesync";

interface MainPageProps {
  onNavigate: (page: Page) => void;
}

export const MainPage: FC<MainPageProps> = ({ onNavigate }) => {
  const [stats, setStats] = useState<SyncStats | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<SyncProgress | null>(null);
  const [status, setStatus] = useState("");
  const [preview, setPreview] = useState<SyncPreview | null>(null);
  const [skipPreview, setSkipPreview] = useState(false);
  const [loading, setLoading] = useState(false);
  const [logLevel, setLogLevel] = useState("warn");
  const [retroarchWarning, setRetroarchWarning] = useState<{ warning: boolean; current?: string } | null>(null);
  const [retroarchFixStatus, setRetroarchFixStatus] = useState("");
  const [migration, setMigration] = useState<MigrationStatus>(getMigrationState());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(() => {
      // Read directly from module-level store — no async callable, no WebSocket
      const progress = getSyncProgress();
      setSyncProgress(progress);

      if (!progress.running) {
        stopPolling();
        setSyncing(false);
        setLoading(false);
        if (statusTimeoutRef.current) clearTimeout(statusTimeoutRef.current);
        setStatus(progress.message || "Sync finished");
        statusTimeoutRef.current = setTimeout(() => setStatus(""), 8000);
        getSyncStats().then(setStats);
      }
    }, 250);
  };

  useEffect(() => {
    getSyncStats().then(setStats);
    testConnection().then((r) => setConnected(r.success));
    getSettings().then((s) => {
      setLogLevel(s.log_level ?? "warn");
      if (s.retroarch_input_check) {
        setRetroarchWarning(s.retroarch_input_check);
      }
    });

    // Check if a sync is already in progress (handles QAM close/reopen)
    const progress = getSyncProgress();
    if (progress.running) {
      setSyncing(true);
      setLoading(true);
      setSyncProgress(progress);
      startPolling();
    }

    const unsubMigration = onMigrationChange(() => setMigration(getMigrationState()));
    return () => {
      stopPolling();
      unsubMigration();
      if (statusTimeoutRef.current) clearTimeout(statusTimeoutRef.current);
    };
  }, []);

  const handleSync = async () => {
    setLoading(true);
    setSyncing(true);
    setStatus("");
    setPreview(null);
    setSyncProgress({ running: true, phase: "starting", message: "Starting sync..." });
    try {
      const result = await syncPreview();
      if (result.success) {
        if (skipPreview && (result.summary.new_count + result.summary.changed_count + result.summary.remove_count > 0)) {
          // Auto-apply: skip preview UI
          setSyncProgress({ running: true, phase: "applying", message: "Applying changes..." });
          const applyResult = await syncApplyDelta(result.preview_id);
          if (applyResult.success) {
            startPolling();
          } else {
            setStatus(applyResult.message);
            setSyncing(false);
            setLoading(false);
          }
        } else if (skipPreview) {
          // Nothing to sync — show brief status
          await syncCancelPreview();
          setStatus("Everything is up to date");
          setSyncing(false);
          setLoading(false);
        } else {
          setPreview(result);
          setSyncing(false);
          setLoading(false);
        }
      } else {
        setStatus(result.message || "Preview failed");
        setSyncing(false);
        setLoading(false);
      }
    } catch {
      setStatus("Failed to start sync");
      setSyncing(false);
      setLoading(false);
    }
  };

  const handleApply = async () => {
    if (!preview) return;
    setLoading(true);
    setSyncing(true);
    setSyncProgress({ running: true, phase: "applying", message: "Applying changes..." });
    try {
      const result = await syncApplyDelta(preview.preview_id);
      if (result.success) {
        setPreview(null);
        startPolling();
      } else {
        setStatus(result.message);
        setSyncing(false);
        setLoading(false);
      }
    } catch {
      setStatus("Failed to apply sync");
      setSyncing(false);
      setLoading(false);
    }
  };

  const handleDismiss = async () => {
    setPreview(null);
    setStatus("");
    try {
      await syncCancelPreview();
    } catch {
      // ignore
    }
  };

  const handleCancel = async () => {
    if (preview) {
      await handleDismiss();
      setSyncing(false);
      setLoading(false);
      return;
    }
    try {
      requestSyncCancel();
      const result = await cancelSync();
      setStatus(result.message);
    } catch {
      setStatus("Failed to cancel sync");
    }
  };

  // Steam's ProgressBarWithInfo nProgress uses percentage (0-100), not fraction (0-1)
  const progressFraction = syncProgress?.total
    ? ((syncProgress.current ?? 0) / syncProgress.total) * 100
    : undefined;

  const formatProgressText = (progress: SyncProgress | null): string => {
    if (!progress) return "Syncing...";
    const step = progress.step && progress.totalSteps
      ? `[${progress.step}/${progress.totalSteps}] `
      : "";
    const msg = progress.message || "Syncing...";
    // Truncate to ~40 chars to prevent multi-line jumping in the QAM panel
    const maxLen = 40 - step.length;
    const truncated = msg.length > maxLen ? msg.slice(0, maxLen - 1) + "\u2026" : msg;
    return step + truncated;
  };

  const formatLastSync = (iso: string | null): string => {
    if (!iso) return "Never";
    try {
      const d = new Date(iso);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 1) return "Just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      const diffDays = Math.floor(diffHours / 24);
      return `${diffDays}d ago`;
    } catch {
      return iso;
    }
  };

  return (
    <>
      <PanelSection title="Status">
        <PanelSectionRow>
          <Field
            label="Connection"
            description={
              connected === null
                ? "Checking..."
                : connected
                  ? "Connected"
                  : "Not connected"
            }
          />
        </PanelSectionRow>
        {stats && (
          <>
            <PanelSectionRow>
              <Field
                label="Last sync"
                description={formatLastSync(stats.last_sync)}
              />
            </PanelSectionRow>
            {stats.roms > 0 && (
              <PanelSectionRow>
                <Field
                  label="Library"
                  description={`${stats.roms} ROMs from ${stats.platforms} platforms`}
                />
              </PanelSectionRow>
            )}
          </>
        )}
        {retroarchWarning && retroarchWarning.warning && (
          <PanelSectionRow>
            <Field
              label="RetroArch: input_driver issue"
              description={`Using "${retroarchWarning.current}" — controllers may not work in menus. See Warning section below.`}
            />
          </PanelSectionRow>
        )}
        {migration.pending && (
          <>
            <PanelSectionRow>
              <div style={{ padding: "8px 12px", backgroundColor: "rgba(212, 167, 44, 0.15)", borderLeft: "3px solid #d4a72c", borderRadius: "4px" }}>
                <div style={{ fontSize: "13px", fontWeight: "bold", color: "#d4a72c", marginBottom: "4px" }}>
                  {"\u26A0\uFE0F"} RetroDECK location changed
                </div>
                <div style={{ fontSize: "12px", color: "rgba(255, 255, 255, 0.7)" }}>
                  {(migration.roms_count ?? 0) + (migration.bios_count ?? 0) + (migration.saves_count ?? 0)} file(s) need migration ({migration.roms_count ?? 0} ROMs, {migration.bios_count ?? 0} BIOS, {migration.saves_count ?? 0} saves)
                </div>
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => onNavigate("connection")}>
                Go to Settings
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title="Sync">
        {preview ? (
          <>
            <PanelSectionRow>
              <Field
                label="Preview"
                description={
                  preview.summary.new_count + preview.summary.changed_count + preview.summary.remove_count === 0
                    ? "Everything is up to date."
                    : `${preview.summary.new_count} new, ${preview.summary.changed_count} updated, ${preview.summary.unchanged_count} unchanged` +
                      (preview.summary.remove_count > 0
                        ? `\n${preview.summary.remove_count} to remove` +
                          (preview.summary.disabled_platform_remove_count > 0
                            ? ` (${preview.summary.disabled_platform_remove_count} from disabled platforms)`
                            : "")
                        : "")
                }
              />
            </PanelSectionRow>
            {preview.summary.new_count + preview.summary.changed_count + preview.summary.remove_count > 0 ? (
              <>
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={handleApply}>
                    Apply Sync
                  </ButtonItem>
                </PanelSectionRow>
                <PanelSectionRow>
                  <ButtonItem layout="below" onClick={handleDismiss}>
                    Cancel
                  </ButtonItem>
                </PanelSectionRow>
              </>
            ) : (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={handleDismiss}>
                  Dismiss
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        ) : !syncing ? (
          <>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleSync}
                disabled={loading || connected === false}
              >
                Sync Library
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Skip Preview"
                description="Apply changes immediately without preview"
                checked={skipPreview}
                onChange={setSkipPreview}
              />
            </PanelSectionRow>
          </>
        ) : (
          <>
            {syncProgress && syncProgress.phase === "applying" ? (
              <PanelSectionRow>
                <ProgressBarWithInfo
                  indeterminate={progressFraction === undefined}
                  nProgress={progressFraction}
                  sOperationText={formatProgressText(syncProgress)}
                />
              </PanelSectionRow>
            ) : (
              <PanelSectionRow>
                <Field
                  label={
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <Spinner width={16} height={16} />
                      {syncProgress?.message || "Syncing..."}
                    </div>
                  }
                />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={handleCancel}>
                Cancel Sync
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        {status && !syncing && !preview && (
          <PanelSectionRow>
            <Field label={status} />
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Settings">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("connection")}>
            Connection Settings
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("platforms")}>
            Platforms
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("savesync")}>
            Save Sync
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("downloads")}>
            Downloads
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("bios")}>
            BIOS Files
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => onNavigate("danger")}>
            Danger Zone
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {retroarchWarning && retroarchWarning.warning && (
        <PanelSection title="Warning">
          <PanelSectionRow>
            <Field
              label={`RetroArch input_driver: "${retroarchWarning.current}"`}
              description="Controller navigation in RetroArch menus may not work with this setting."
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={async () => {
                setRetroarchFixStatus("Applying...");
                try {
                  const result = await fixRetroarchInputDriver();
                  setRetroarchFixStatus(result.message);
                  if (result.success) {
                    setRetroarchWarning(null);
                  }
                } catch {
                  setRetroarchFixStatus("Failed to apply fix");
                }
              }}
            >
              Change to sdl2
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <Field
              label=""
              description="This modifies your RetroArch config. Use with caution — if controllers stop working, revert manually."
            />
          </PanelSectionRow>
          {retroarchFixStatus && (
            <PanelSectionRow>
              <Field label={retroarchFixStatus} />
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <PanelSection title="Advanced">
        <PanelSectionRow>
          <DropdownItem
            label="Log Level"
            description="Controls which frontend messages are written to the plugin log file"
            rgOptions={[
              { data: "error", label: "Error" },
              { data: "warn", label: "Warn" },
              { data: "info", label: "Info" },
              { data: "debug", label: "Debug" },
            ]}
            selectedOption={logLevel}
            onChange={(option) => {
              setLogLevel(option.data);
              saveLogLevel(option.data);
            }}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};
