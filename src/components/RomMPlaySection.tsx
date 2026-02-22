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
import { basicAppDetailsSectionStylerClasses } from "@decky/ui";
import { CustomPlayButton } from "./CustomPlayButton";
import {
  getRomBySteamAppId,
  getSaveSyncSettings,
  getSaveStatus,
  getPendingConflicts,
  checkPlatformBios,
  debugLog,
} from "../api/backend";
import type { BiosStatus, SaveSyncSettings, SaveStatus, PendingConflict } from "../types";

interface RomMPlaySectionProps {
  appId: number;
}

interface InfoState {
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
    lastPlayed: initialLastPlayed,
    playtime: initialPlaytime,
    saveSyncEnabled: false,
    saveSyncStatus: null,
    saveSyncLabel: "",
    biosNeeded: false,
    biosStatus: null,
    biosLabel: "",
  });

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

        // Fetch save sync settings, save status, conflicts, and BIOS in parallel
        const [saveSyncSettings, saveStatus, conflictsResult, biosResult] = await Promise.all([
          getSaveSyncSettings().catch((): SaveSyncSettings => ({
            save_sync_enabled: false,
            conflict_mode: "newest_wins",
            sync_before_launch: false,
            sync_after_exit: false,
            clock_skew_tolerance_sec: 60,
          })),
          getSaveStatus(romId).catch((): SaveStatus | null => null),
          getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
          checkPlatformBios(platformSlug).catch((): BiosStatus => ({ needs_bios: false })),
        ]);

        if (cancelled) return;

        // Process save sync info
        let saveSyncStatus: "synced" | "conflict" | "none" | null = null;
        let saveSyncLabel = "";
        if (saveSyncSettings.save_sync_enabled) {
          const hasConflict = conflictsResult.conflicts.some((c) => c.rom_id === romId);
          if (hasConflict) {
            saveSyncStatus = "conflict";
            saveSyncLabel = "Conflict";
          } else if (saveStatus && saveStatus.files.length > 0) {
            const lastSync = saveStatus.files
              .map((f) => f.last_sync_at)
              .filter(Boolean)
              .sort()
              .reverse()[0];
            if (lastSync) {
              saveSyncStatus = "synced";
              const syncDate = new Date(lastSync);
              const diffMs = Date.now() - syncDate.getTime();
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
          // Override playtime if RomM has tracked data
          ...(playtime ? { playtime } : {}),
          saveSyncEnabled: saveSyncSettings.save_sync_enabled,
          saveSyncStatus,
          saveSyncLabel,
          biosNeeded,
          biosStatus,
          biosLabel,
        }));
      } catch (e) {
        debugLog(`RomMPlaySection: loadInfo error: ${e}`);
      }
    }

    loadInfo();
    return () => { cancelled = true; };
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

  return createElement("div", {
    "data-romm": "true",
    className: `romm-play-section-row ${basicAppDetailsSectionStylerClasses?.PlaySection || ""}`.trim(),
    style: {
      display: "flex",
      alignItems: "center",
      gap: "20px",
      padding: "16px 2.8vw",
      background: "rgba(14, 20, 27, 0.33)",
      boxSizing: "border-box",
    },
  },
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
  );
};
