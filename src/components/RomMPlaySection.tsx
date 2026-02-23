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

import { useState, useEffect, FC, createElement } from "react";
import { toaster } from "@decky/api";
import {
  basicAppDetailsSectionStylerClasses,
  Focusable,
  Menu,
  MenuItem,
  MenuSeparator,
  showContextMenu,
} from "@decky/ui";
import { FaGamepad, FaCog } from "react-icons/fa";
import { CustomPlayButton } from "./CustomPlayButton";
import {
  getRomBySteamAppId,
  getSaveSyncSettings,
  getSaveStatus,
  checkPlatformBios,
  getSgdbArtworkBase64,
  getRomMetadata,
  removeRom,
  downloadAllFirmware,
  syncRomSaves,
  saveShortcutIcon,
  debugLog,
} from "../api/backend";
import type { BiosStatus, SaveSyncSettings, SaveStatus } from "../types";

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
  const [actionPending, setActionPending] = useState<string | null>(null);

  // Load async info (save sync, BIOS) — play button and playtime render immediately
  useEffect(() => {
    let cancelled = false;

    async function loadInfo() {
      try {

        // Get ROM info for platform slug and rom ID
        const rom = await getRomBySteamAppId(appId);
        if (cancelled || !rom) return;

        const romId: number = rom.rom_id;
        const platformSlug: string = rom.platform_slug;

        // Fetch save sync settings, save status, and BIOS in parallel
        const [saveSyncSettings, saveStatus, biosResult] = await Promise.all([
          getSaveSyncSettings().catch((): SaveSyncSettings => ({
            save_sync_enabled: false,
            conflict_mode: "newest_wins",
            sync_before_launch: false,
            sync_after_exit: false,
            clock_skew_tolerance_sec: 60,
          })),
          getSaveStatus(romId).catch((): SaveStatus | null => null),
          checkPlatformBios(platformSlug).catch((): BiosStatus => ({ needs_bios: false })),
        ]);

        if (cancelled) return;

        // Process save sync info
        let saveSyncStatus: "synced" | "conflict" | "none" | null = null;
        let saveSyncLabel = "";
        if (saveSyncSettings.save_sync_enabled) {
          // Use real-time conflict detection from get_save_status (calls _detect_conflict per file)
          const hasConflict = saveStatus?.files?.some((f) => f.status === "conflict") ?? false;
          if (hasConflict) {
            saveSyncStatus = "conflict";
            saveSyncLabel = "Conflict";
          } else if (saveStatus && saveStatus.files.length > 0) {
            const lastCheck = saveStatus.last_sync_check_at;
            if (lastCheck) {
              saveSyncStatus = "synced";
              const checkDate = new Date(lastCheck);
              const diffMs = Date.now() - checkDate.getTime();
              const diffMin = Math.floor(diffMs / 60000);
              if (diffMin < 1) saveSyncLabel = "Just now";
              else if (diffMin < 60) saveSyncLabel = `${diffMin}m ago`;
              else if (diffMin < 1440) saveSyncLabel = `${Math.floor(diffMin / 60)}h ago`;
              else saveSyncLabel = `${Math.floor(diffMin / 1440)}d ago`;
            } else {
              saveSyncStatus = "none";
              saveSyncLabel = "Not synced";
            }
          } else {
            saveSyncStatus = "none";
            saveSyncLabel = "No saves";
          }
        }

        // Process BIOS info
        let biosNeeded = false;
        let biosStatus: "ok" | "partial" | "missing" | null = null;
        let biosLabel = "";
        if (biosResult.needs_bios) {
          biosNeeded = true;
          biosStatus = getBiosLevel(biosResult);
          biosLabel = formatBiosLabel(biosResult);
        }

        // Update playtime from RomM save sync data (more accurate than Steam's native tracking)
        let playtime = "";
        if (saveStatus?.playtime?.total_seconds && saveStatus.playtime.total_seconds > 0) {
          playtime = formatPlaytime(Math.floor(saveStatus.playtime.total_seconds / 60));
        }

        if (cancelled) return;
        setInfo((prev) => ({
          ...prev,
          romId,
          romName: rom.name || "",
          platformSlug,
          // Override playtime if RomM has tracked data
          ...(playtime ? { playtime } : {}),
          saveSyncEnabled: saveSyncSettings.save_sync_enabled,
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
      } catch (e) {
        debugLog(`RomMPlaySection: loadInfo error: ${e}`);
      }
    }

    loadInfo();

    // Listen for conflict resolution / save sync changes from sibling components
    const onDataChanged = async (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.type !== "save_sync") return;
      const romId = info.romId ?? detail.rom_id;
      if (!romId) return;
      const saveStatus = await getSaveStatus(romId).catch((): SaveStatus | null => null);
      const hasConflict = saveStatus?.files?.some((f) => f.status === "conflict") ?? false;
      let saveSyncStatus: "synced" | "conflict" | "none" = "none";
      let saveSyncLabel = "";
      if (hasConflict) {
        saveSyncStatus = "conflict";
        saveSyncLabel = "Conflict";
      } else if (saveStatus && saveStatus.files.length > 0) {
        saveSyncStatus = "synced";
        saveSyncLabel = "Just now";
      }
      setInfo((prev) => ({ ...prev, saveSyncStatus, saveSyncLabel }));
    };
    window.addEventListener("romm_data_changed", onDataChanged);

    return () => {
      cancelled = true;
      window.removeEventListener("romm_data_changed", onDataChanged);
    };
  }, [appId]);

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
        toaster.toast({ title: "RomM Sync", body: `Saves synced (${result.synced} files)` });
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

  const showRomMMenu = (e: Event) => {
    showContextMenu(
      createElement(Menu, { label: "RomM Actions" },
        createElement(MenuItem, { key: "refresh-artwork", onClick: handleRefreshArtwork }, "Refresh Artwork"),
        createElement(MenuItem, { key: "refresh-metadata", onClick: handleRefreshMetadata }, "Refresh Metadata"),
        createElement(MenuItem, { key: "sync-saves", onClick: handleSyncSaves }, "Sync Save Files"),
        createElement(MenuItem, { key: "download-bios", onClick: handleDownloadBios }, "Download BIOS"),
        createElement(MenuSeparator, { key: "sep" }),
        createElement(MenuItem, { key: "uninstall", tone: "destructive", onClick: handleUninstall }, "Uninstall"),
      ),
      (e.currentTarget ?? e.target) as HTMLElement,
    );
  };

  const showSteamMenu = (e: Event) => {
    showContextMenu(
      createElement(Menu, { label: "Steam" },
        createElement(MenuItem, { key: "properties", onClick: () => {
          SteamClient.Apps.OpenAppSettingsDialog(appId, "");
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
      createElement(Focusable, {
        style: { display: "flex" },
        focusWithinClassName: "romm-gear-focused",
        onActivate: showRomMMenu,
      } as any,
        createElement("button", {
          className: "romm-gear-btn",
          onClick: showRomMMenu,
          title: "RomM Actions",
        },
          createElement(FaGamepad, { size: 18, color: "#553e98" }),
        ),
      ),
      // Steam properties button
      createElement(Focusable, {
        style: { display: "flex" },
        focusWithinClassName: "romm-gear-focused",
        onActivate: showSteamMenu,
      } as any,
        createElement("button", {
          className: "romm-gear-btn",
          onClick: showSteamMenu,
          title: "Steam Properties",
        },
          createElement(FaCog, { size: 18, color: "#8f98a0" }),
        ),
      ),
    ),
  );
};
