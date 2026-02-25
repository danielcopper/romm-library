/**
 * RomMPlaySection — wraps CustomPlayButton and adds info items to its right,
 * mimicking Steam's native PlaySection layout:
 *
 *   [▶ Play ▾]   LAST PLAYED    PLAYTIME    ACHIEVEMENTS    SAVE SYNC    BIOS
 *                24. Jan.       14 Hours    To be impl.     ✅ 2h ago    🟢 OK
 *
 * Uses our own romm-play-section-row CSS class on the root.
 * Individual info items use our own romm-info-* CSS classes.
 * Save Sync and BIOS items only appear when relevant.
 */

import { useState, useEffect, useRef, FC, createElement } from "react";
import { toaster } from "@decky/api";
import {
  basicAppDetailsSectionStylerClasses,
  ConfirmModal,
  DialogButton,
  Focusable,
  Menu,
  MenuItem,
  MenuSeparator,
  showContextMenu,
  showModal,
} from "@decky/ui";
import { FaGamepad, FaCog } from "react-icons/fa";
import { CustomPlayButton } from "./CustomPlayButton";
import {
  getCachedGameDetail,
  testConnection,
  checkSaveStatusLightweight,
  getSaveStatus,
  checkPlatformBios,
  getSgdbArtworkBase64,
  getRomMetadata,
  removeRom,
  downloadAllFirmware,
  syncRomSaves,
  deleteLocalSaves,
  saveShortcutIcon,
  debugLog,
} from "../api/backend";
import type { BiosStatus, SaveStatus } from "../types";

/** Track which appIds have had auto-artwork applied this session */
const artworkApplied = new Set<number>();

/** Fetch SGDB artwork (hero, logo, wide grid, icon) and apply to Steam.
 *  Returns count of successfully applied images. */
async function applyArtwork(romId: number, appId: number): Promise<number> {
  const results = await Promise.all([
    getSgdbArtworkBase64(romId, 1).catch(() => ({ base64: null, no_api_key: false })),
    getSgdbArtworkBase64(romId, 2).catch(() => ({ base64: null, no_api_key: false })),
    getSgdbArtworkBase64(romId, 3).catch(() => ({ base64: null, no_api_key: false })),
    getSgdbArtworkBase64(romId, 4).catch(() => ({ base64: null, no_api_key: false })),
  ]);

  if (results.some((r) => r.no_api_key)) return -1;

  let applied = 0;
  // SGDB type 1 = hero → Steam assetType 1
  if (results[0].base64) {
    await SteamClient.Apps.SetCustomArtworkForApp(appId, results[0].base64, "png", 1);
    applied++;
  }
  // SGDB type 2 = logo → Steam assetType 2
  if (results[1].base64) {
    await SteamClient.Apps.SetCustomArtworkForApp(appId, results[1].base64, "png", 2);
    applied++;
  }
  // SGDB type 3 = wide grid → Steam assetType 3
  if (results[2].base64) {
    await SteamClient.Apps.SetCustomArtworkForApp(appId, results[2].base64, "png", 3);
    applied++;
  }
  // Type 4 = icon (VDF-based)
  if (results[3].base64) {
    await saveShortcutIcon(appId, results[3].base64);
    applied++;
  }

  return applied;
}

interface RomMPlaySectionProps {
  appId: number;
}

type ConnectionState = "checking" | "connected" | "offline";

interface InfoState {
  romId: number | null;
  romName: string;
  platformSlug: string;
  lastPlayed: string;
  playtime: string;
  saveSyncEnabled: boolean;
  saveSyncStatus: "synced" | "conflict" | "none" | null;
  saveSyncLabel: string;
  biosNeeded: boolean;
  biosStatus: "ok" | "partial" | "missing" | null;
  biosLabel: string;
}

/** Format a Unix timestamp (seconds) as a human-readable date string */
function formatLastPlayed(timestamp: number): string {
  if (!timestamp || timestamp <= 0) return "Never";
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;

  // Format as "24. Jan." style
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = date.getDate();
  const month = months[date.getMonth()];
  const year = date.getFullYear();
  if (year === now.getFullYear()) return `${day}. ${month}.`;
  return `${day}. ${month}. ${year}`;
}

/** Format minutes of playtime into a readable string */
function formatPlaytime(minutes: number): string {
  if (!minutes || minutes <= 0) return "None";
  if (minutes < 60) return `${minutes} Min`;
  const hours = Math.floor(minutes / 60);
  const remainingMin = minutes % 60;
  if (remainingMin === 0) return hours === 1 ? "1 Hour" : `${hours} Hours`;
  return `${hours}h ${remainingMin}m`;
}

/** Format BIOS status counts into a label */
function formatBiosLabel(bios: BiosStatus): string {
  if (bios.all_downloaded) return "OK";
  if ((bios.local_count ?? 0) > 0) return `${bios.local_count}/${bios.server_count}`;
  return "Missing";
}

/** Determine BIOS status level */
function getBiosLevel(bios: BiosStatus): "ok" | "partial" | "missing" {
  if (bios.all_downloaded) return "ok";
  if ((bios.local_count ?? 0) > 0) return "partial";
  return "missing";
}

/** Compute save sync display status and label from a SaveStatus response */
function computeSaveSyncDisplay(saveStatus: SaveStatus | null): { status: "synced" | "conflict" | "none"; label: string } {
  const hasConflict = saveStatus?.files?.some((f) => f.status === "conflict") ?? false;
  if (hasConflict) return { status: "conflict", label: "Conflict" };

  const hasLocalFiles = saveStatus?.files?.some((f) => f.local_path || f.status === "synced" || f.status === "upload") ?? false;
  if (hasLocalFiles) {
    const lastCheck = saveStatus?.last_sync_check_at;
    if (lastCheck) {
      const diffMs = Date.now() - new Date(lastCheck).getTime();
      const diffMin = Math.floor(diffMs / 60000);
      let label: string;
      if (diffMin < 1) label = "Just now";
      else if (diffMin < 60) label = `${diffMin}m ago`;
      else if (diffMin < 1440) label = `${Math.floor(diffMin / 60)}h ago`;
      else label = `${Math.floor(diffMin / 1440)}d ago`;
      return { status: "synced", label };
    }
    return { status: "synced", label: "Not synced" };
  }

  if (saveStatus && saveStatus.files.length > 0) return { status: "none", label: "No local saves" };
  return { status: "none", label: "No saves" };
}

import { setRommConnectionState } from "../utils/connectionState";

export const RomMPlaySection: FC<RomMPlaySectionProps> = ({ appId }) => {
  // Read playtime from Steam's own overview synchronously (already written by metadataPatches)
  // This avoids an unnecessary render from setting it inside the async effect.
  const overview = appStore.GetAppOverviewByAppID(appId);
  const initialLastPlayed = formatLastPlayed(overview?.rt_last_time_played ?? 0);
  const initialPlaytime = formatPlaytime(overview?.minutes_playtime_forever ?? 0);

  const [info, setInfo] = useState<InfoState>({
    romId: null,
    romName: "",
    platformSlug: "",
    lastPlayed: initialLastPlayed,
    playtime: initialPlaytime,
    saveSyncEnabled: false,
    saveSyncStatus: null,
    saveSyncLabel: "",
    biosNeeded: false,
    biosStatus: null,
    biosLabel: "",
  });
  const [connectionState, setConnectionState] = useState<ConnectionState>("checking");
  const [actionPending, setActionPending] = useState<string | null>(null);
  const romIdRef = useRef<number | null>(null);

  // Cache-first load: render instantly from cached data, then check connection in background
  useEffect(() => {
    let cancelled = false;

    async function loadCached() {
      try {
        const cached = await getCachedGameDetail(appId);
        if (cancelled || !cached.found) return;

        const romId = cached.rom_id!;
        romIdRef.current = romId;

        // Process save sync from cached data
        let saveSyncStatus: "synced" | "conflict" | "none" | null = null;
        let saveSyncLabel = "";
        if (cached.save_sync_enabled && cached.save_status) {
          // Build a minimal SaveStatus-compatible object for computeSaveSyncDisplay
          const pseudoStatus: SaveStatus = {
            rom_id: romId,
            files: cached.save_status.files.map((f) => ({
              filename: f.filename,
              status: f.status as "skip" | "download" | "upload" | "conflict",
              local_path: null,
              local_hash: null,
              local_mtime: null,
              local_size: null,
              server_save_id: null,
              server_updated_at: null,
              server_size: null,
              last_sync_at: f.last_sync_at ?? null,
            })),
            playtime: { total_seconds: 0, session_count: 0, last_session_start: null, last_session_duration_sec: null },
            device_id: "",
            last_sync_check_at: cached.save_status.last_sync_check_at ?? null,
          };
          const display = computeSaveSyncDisplay(pseudoStatus);
          saveSyncStatus = display.status;
          saveSyncLabel = display.label;
        }

        // Process BIOS from cached data
        let biosNeeded = false;
        let biosStatus: "ok" | "partial" | "missing" | null = null;
        let biosLabel = "";
        if (cached.bios_status) {
          biosNeeded = true;
          const b = cached.bios_status;
          if (b.all_downloaded) {
            biosStatus = "ok";
            biosLabel = "OK";
          } else if (b.downloaded > 0) {
            biosStatus = "partial";
            biosLabel = `${b.downloaded}/${b.total}`;
          } else {
            biosStatus = "missing";
            biosLabel = "Missing";
          }
        }

        if (cancelled) return;
        setInfo((prev) => ({
          ...prev,
          romId,
          romName: cached.rom_name || "",
          platformSlug: cached.platform_slug || "",
          saveSyncEnabled: cached.save_sync_enabled ?? false,
          saveSyncStatus,
          saveSyncLabel,
          biosNeeded,
          biosStatus,
          biosLabel,
        }));

        // Auto-apply SGDB artwork on first visit (fire-and-forget)
        if (!artworkApplied.has(appId)) {
          artworkApplied.add(appId);
          applyArtwork(romId, appId).catch((e) => debugLog(`Auto-artwork error: ${e}`));
        }

        // Background: fetch metadata if missing or stale (>7 days)
        const METADATA_TTL_SEC = 7 * 24 * 3600;
        const metaCachedAt = (cached.metadata as Record<string, unknown> | null)?.cached_at as number | undefined;
        const metaStale = !metaCachedAt || (Date.now() / 1000 - metaCachedAt) > METADATA_TTL_SEC;
        if (romId && (!cached.metadata || metaStale)) {
          getRomMetadata(romId).catch((e) => debugLog(`Background metadata fetch error: ${e}`));
        }
      } catch (e) {
        debugLog(`RomMPlaySection: loadCached error: ${e}`);
      }
    }

    loadCached();

    // Listen for conflict resolution / save sync changes from sibling components
    const onDataChanged = async (e: Event) => {
      const detail = (e as CustomEvent).detail;

      // Handle save sync settings toggle (show/hide save sync info item)
      if (detail?.type === "save_sync_settings") {
        const enabled = detail.save_sync_enabled as boolean;
        if (enabled) {
          const rid = romIdRef.current;
          if (rid) {
            const saveStatus = await getSaveStatus(rid).catch((): SaveStatus | null => null);
            const { status: ss, label: sl } = computeSaveSyncDisplay(saveStatus);
            setInfo((prev) => ({ ...prev, saveSyncEnabled: true, saveSyncStatus: ss, saveSyncLabel: sl }));
          } else {
            setInfo((prev) => ({ ...prev, saveSyncEnabled: true }));
          }
        } else {
          setInfo((prev) => ({ ...prev, saveSyncEnabled: false, saveSyncStatus: null, saveSyncLabel: "" }));
        }
        return;
      }

      if (detail?.type !== "save_sync") return;
      const romId = romIdRef.current ?? detail.rom_id;
      if (!romId) return;
      // If event specifies a rom_id, skip if it's not for this game
      if (detail.rom_id && romIdRef.current && detail.rom_id !== romIdRef.current) return;
      const saveStatus = await getSaveStatus(romId).catch((): SaveStatus | null => null);
      const { status: saveSyncStatus, label: saveSyncLabel } = computeSaveSyncDisplay(saveStatus);
      setInfo((prev) => ({ ...prev, saveSyncStatus, saveSyncLabel }));
    };
    window.addEventListener("romm_data_changed", onDataChanged);

    return () => {
      cancelled = true;
      window.removeEventListener("romm_data_changed", onDataChanged);
    };
  }, [appId]);

  // Background connection check — runs after initial cached render
  // If connected + installed + save sync enabled, also runs lightweight save status check
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const result = await Promise.race([
          testConnection(),
          new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 2000)),
        ]);
        if (cancelled) return;
        const connected = result.success;
        const connState = connected ? "connected" : "offline";
        setRommConnectionState(connState);
        setConnectionState(connState);
        window.dispatchEvent(new CustomEvent("romm_connection_changed", { detail: { state: connState } }));

        // If connected, do lightweight save status check to detect new conflicts
        const romId = romIdRef.current;
        if (connected && romId && info.saveSyncEnabled) {
          try {
            const saveStatus = await checkSaveStatusLightweight(romId);
            if (cancelled) return;
            const hasConflict = saveStatus?.files?.some((f: { status: string }) => f.status === "conflict") ?? false;
            // Always notify CustomPlayButton with fresh conflict status
            window.dispatchEvent(new CustomEvent("romm_data_changed", {
              detail: { type: "save_sync", rom_id: romId, has_conflict: hasConflict },
            }));
            // Update save sync display in PlaySection info items
            const { status: ss, label: sl } = computeSaveSyncDisplay(saveStatus);
            setInfo((prev) => ({ ...prev, saveSyncStatus: ss, saveSyncLabel: sl }));
          } catch (e) {
            debugLog(`RomMPlaySection: lightweight save check error: ${e}`);
          }
        }
      } catch {
        if (!cancelled) {
          setRommConnectionState("offline");
          setConnectionState("offline");
          window.dispatchEvent(new CustomEvent("romm_connection_changed", { detail: { state: "offline" } }));
        }
      }
    };
    check();
    return () => { cancelled = true; };
  }, [info.saveSyncEnabled]);

  // Helper: create an info item with header and value (Steam's two-line pattern)
  const infoItem = (key: string, header: string, value: string, extraClass?: string) =>
    createElement("div", {
      key,
      className: `romm-info-item ${extraClass || ""}`.trim(),
    },
      createElement("div", { className: "romm-info-header" }, header),
      createElement("div", { className: "romm-info-value" }, value),
    );

  // Helper: info item with a colored status dot
  const statusInfoItem = (key: string, header: string, value: string, color: string) =>
    createElement("div", {
      key,
      className: "romm-info-item",
    },
      createElement("div", { className: "romm-info-header" }, header),
      createElement("div", {
        className: "romm-info-value",
        style: { display: "flex", alignItems: "center", gap: "6px" },
      },
        createElement("span", {
          className: "romm-status-dot",
          style: { backgroundColor: color },
        }),
        value,
      ),
    );

  // --- Gear button action handlers ---

  const handleRefreshArtwork = async () => {
    if (actionPending) return;
    if (!info.romId) {
      toaster.toast({ title: "RomM Sync", body: "ROM info not loaded yet" });
      return;
    }
    setActionPending("artwork");
    try {
      const applied = await applyArtwork(info.romId, appId);
      if (applied === -1) {
        toaster.toast({ title: "RomM Sync", body: "Set a SteamGridDB API key in settings first" });
      } else if (applied > 0) {
        toaster.toast({ title: "RomM Sync", body: `Artwork refreshed (${applied}/4 images applied)` });
      } else {
        toaster.toast({ title: "RomM Sync", body: "No artwork found" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Failed to refresh artwork" });
    } finally {
      setActionPending(null);
    }
  };

  const handleRefreshMetadata = async () => {
    if (actionPending || !info.romId) return;
    setActionPending("metadata");
    try {
      await getRomMetadata(info.romId);
      toaster.toast({ title: "RomM Sync", body: "Metadata refreshed" });
      window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "metadata", rom_id: info.romId } }));
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Failed to refresh metadata" });
    } finally {
      setActionPending(null);
    }
  };

  const handleSyncSaves = async () => {
    if (actionPending || !info.romId) return;
    setActionPending("savesync");
    try {
      const result = await syncRomSaves(info.romId);
      if (result.success) {
        const n = result.synced ?? 0;
        const label = n === 0 ? "no files updated" : n === 1 ? "1 file updated" : `${n} files updated`;
        toaster.toast({ title: "RomM Sync", body: `Saves synced (${label})` });
        window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "save_sync", rom_id: info.romId } }));
        // Refresh save sync status — last_sync_check_at was just set by the backend
        setInfo((prev) => ({ ...prev, saveSyncStatus: "synced" as const, saveSyncLabel: "Just now" }));
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "Save sync failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Save sync failed" });
    } finally {
      setActionPending(null);
    }
  };

  const handleDownloadBios = async () => {
    if (actionPending || !info.platformSlug) return;
    setActionPending("bios");
    try {
      const result = await downloadAllFirmware(info.platformSlug);
      if (result.success) {
        toaster.toast({ title: "RomM Sync", body: `BIOS downloaded (${result.downloaded ?? 0} files)` });
        window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "bios", platform_slug: info.platformSlug } }));
        // Refresh BIOS status
        const updated = await checkPlatformBios(info.platformSlug).catch((): BiosStatus => ({ needs_bios: false }));
        if (updated.needs_bios) {
          setInfo((prev) => ({
            ...prev,
            biosStatus: getBiosLevel(updated),
            biosLabel: formatBiosLabel(updated),
          }));
        }
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "BIOS download failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "BIOS download failed" });
    } finally {
      setActionPending(null);
    }
  };

  const handleUninstall = async () => {
    if (actionPending || !info.romId) return;
    setActionPending("uninstall");
    try {
      const result = await removeRom(info.romId);
      if (result.success) {
        window.dispatchEvent(new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: info.romId } }));
        toaster.toast({ title: "RomM Sync", body: `${info.romName || "ROM"} uninstalled` });
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "Uninstall failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Uninstall failed" });
    } finally {
      setActionPending(null);
    }
  };

  const handleDeleteSaves = () => {
    if (actionPending || !info.romId) return;
    const romId = info.romId;
    showModal(
      createElement(ConfirmModal, {
        strTitle: "Delete Local Saves",
        strDescription: "This will delete local save files for this game. Make sure saves are synced to RomM first — the next sync will re-download them from the server.",
        strOKButtonText: "Delete",
        strCancelButtonText: "Cancel",
        onOK: async () => {
          setActionPending("deletesaves");
          try {
            const result = await deleteLocalSaves(romId);
            if (result.success) {
              toaster.toast({ title: "RomM Sync", body: result.message });
              // Directly update PlaySection status — no local saves remain
              setInfo((prev) => ({ ...prev, saveSyncStatus: "none" as const, saveSyncLabel: "No saves" }));
              window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "save_sync", rom_id: romId } }));
            } else {
              toaster.toast({ title: "RomM Sync", body: result.message || "Failed to delete saves" });
            }
          } catch {
            toaster.toast({ title: "RomM Sync", body: "Failed to delete saves" });
          } finally {
            setActionPending(null);
          }
        },
      } as any),
    );
  };

  const showRomMMenu = (e: Event) => {
    showContextMenu(
      createElement(Menu, { label: "RomM Actions" },
        createElement(MenuItem, { key: "refresh-artwork", onClick: handleRefreshArtwork }, "Refresh Artwork"),
        createElement(MenuItem, { key: "refresh-metadata", onClick: handleRefreshMetadata }, "Refresh Metadata"),
        createElement(MenuItem, { key: "sync-saves", onClick: handleSyncSaves }, "Sync Save Files"),
        createElement(MenuItem, { key: "download-bios", onClick: handleDownloadBios }, "Download BIOS"),
        createElement(MenuSeparator, { key: "sep" }),
        createElement(MenuItem, { key: "delete-saves", tone: "destructive", onClick: handleDeleteSaves }, "Delete Local Saves"),
        createElement(MenuItem, { key: "uninstall", tone: "destructive", onClick: handleUninstall }, "Uninstall"),
      ),
      (e.currentTarget ?? e.target) as HTMLElement,
    );
  };

  const showSteamMenu = (e: Event) => {
    showContextMenu(
      createElement(Menu, { label: "Steam" },
        createElement(MenuItem, { key: "properties", onClick: () => {
          SteamClient.Apps.OpenAppSettingsDialog(appId, "general");
        } }, "Properties"),
        // TODO: Add to/Remove from Collection and Favorites when APIs are explored
      ),
      (e.currentTarget ?? e.target) as HTMLElement,
    );
  };

  // Build info items array
  const infoItems: ReturnType<typeof createElement>[] = [];

  // Last Played
  if (info.lastPlayed) {
    infoItems.push(infoItem("last-played", "LAST PLAYED", info.lastPlayed));
  }

  // Playtime
  if (info.playtime) {
    infoItems.push(infoItem("playtime", "PLAYTIME", info.playtime));
  }

  // Achievements (static placeholder)
  infoItems.push(infoItem("achievements", "ACHIEVEMENTS", "Not available", "romm-info-muted"));

  // Save Sync (only when enabled)
  if (info.saveSyncEnabled && info.saveSyncStatus) {
    const syncColor =
      info.saveSyncStatus === "synced" ? "#5ba32b"
        : info.saveSyncStatus === "conflict" ? "#d94126"
          : "#8f98a0";
    infoItems.push(statusInfoItem("save-sync", "SAVE SYNC", info.saveSyncLabel, syncColor));
  }

  // BIOS (only when platform needs it)
  if (info.biosNeeded && info.biosStatus) {
    const biosColor =
      info.biosStatus === "ok" ? "#5ba32b"
        : info.biosStatus === "partial" ? "#d4a72c"
          : "#d94126";
    infoItems.push(statusInfoItem("bios", "BIOS", info.biosLabel, biosColor));
  }

  // RomM connection status
  const connColor = connectionState === "connected" ? "#5ba32b"
    : connectionState === "offline" ? "#8f98a0"
      : "#1a9fff";
  const connLabel = connectionState === "connected" ? "Online"
    : connectionState === "offline" ? "Offline"
      : "Checking...";
  const connExtraClass = connectionState === "checking" ? "romm-info-checking" : "";
  infoItems.push(
    createElement("div", {
      key: "romm-status",
      className: `romm-info-item ${connExtraClass}`.trim(),
    },
      createElement("div", { className: "romm-info-header" }, "RomM"),
      createElement("div", {
        className: "romm-info-value",
        style: { display: "flex", alignItems: "center", gap: "6px" },
      },
        createElement("span", {
          className: `romm-status-dot ${connectionState === "checking" ? "romm-status-dot-pulse" : ""}`.trim(),
          style: { backgroundColor: connColor },
        }),
        connLabel,
      ),
    ),
  );

  return createElement(Focusable, {
    "data-romm": "true",
    className: `romm-play-section-row ${basicAppDetailsSectionStylerClasses?.PlaySection || ""}`.trim(),
    "flow-children": "right",
    style: {
      display: "flex",
      alignItems: "center",
      gap: "20px",
      padding: "16px 2.8vw",
      background: "rgba(14, 20, 27, 0.33)",
      boxSizing: "border-box",
    },
  } as any,
    // Play button on the left
    createElement(CustomPlayButton, { appId }),
    // Info items row
    createElement("div", {
      className: "romm-info-items",
      style: {
        display: "flex",
        alignItems: "center",
        gap: "20px",
        flexWrap: "nowrap",
        overflow: "hidden",
      },
    },
      ...infoItems,
    ),
    // Gear icon buttons pushed to the far right
    createElement("div", {
      style: {
        marginLeft: "auto",
        display: "flex",
        alignItems: "center",
        gap: "8px",
        flexShrink: 0,
      },
    },
      // RomM actions button
      createElement(DialogButton, {
        className: "romm-gear-btn",
        onClick: showRomMMenu,
        title: "RomM Actions",
      } as any,
        createElement(FaGamepad, { size: 18, color: "#553e98" }),
      ),
      // Steam properties button
      createElement(DialogButton, {
        className: "romm-gear-btn",
        onClick: showSteamMenu,
        title: "Steam Properties",
      } as any,
        createElement(FaCog, { size: 18, color: "#8f98a0" }),
      ),
    ),
  );
};
