/**
 * RomMGameInfoPanel — metadata and actions panel injected below the PlaySection
 * on RomM game detail pages.
 *
 * Layout:
 *   Status Row:   Install status (Downloaded / Not Installed) + Platform badge
 *   Game Info:    Description, Developer/Publisher, Genre tags, Release date
 *   ROM File:     Filename (only when installed)
 *   BIOS:         Status + Download All (only when platform needs BIOS)
 *   Save Sync:    Status + Sync Now (only when save sync enabled)
 *   Actions:      Refresh Artwork, Refresh Metadata, Uninstall (when installed)
 *
 * Uses createElement throughout (no JSX) to match the RomMPlaySection pattern.
 * CSS classes prefixed with `romm-panel-` are injected separately by styleInjector.
 */

import { useState, useEffect, useRef, FC, createElement, CSSProperties } from "react";
import { toaster } from "@decky/api";
import { Focusable, DialogButton } from "@decky/ui";
import {
  getRomBySteamAppId,
  getRomMetadata,
  getInstalledRom,
  getSgdbArtworkBase64,
  removeRom,
  checkPlatformBios,
  downloadAllFirmware,
  getSaveSyncSettings,
  getSaveStatus,
  getPendingConflicts,
  syncRomSaves,
  resolveConflict,
  debugLog,
} from "../api/backend";
import type { RomMetadata, InstalledRom, BiosStatus, SaveSyncSettings, SaveStatus, PendingConflict } from "../types";

interface RomMGameInfoPanelProps {
  appId: number;
}

interface PanelState {
  loading: boolean;
  romId: number | null;
  romName: string;
  platformName: string;
  platformSlug: string;
  installed: boolean;
  installedRom: InstalledRom | null;
  metadata: RomMetadata | null;
  biosStatus: BiosStatus | null;
  saveSyncEnabled: boolean;
  saveStatus: SaveStatus | null;
  conflicts: PendingConflict[];
  error: boolean;
}

/** Format a Unix timestamp (seconds) as a release date string (e.g. "15 Mar 2003") */
function formatReleaseDate(timestamp: number | null): string | null {
  if (!timestamp || timestamp <= 0) return null;
  const date = new Date(timestamp * 1000);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}

/** Format an ISO datetime string as "22 Feb 2026, 14:32:15" */
function formatSyncDateTime(isoStr: string | null): string {
  if (!isoStr) return "Never synced";
  const date = new Date(isoStr);
  if (isNaN(date.getTime())) return "Never synced";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const d = date.getDate();
  const mon = months[date.getMonth()];
  const y = date.getFullYear();
  const h = String(date.getHours()).padStart(2, "0");
  const m = String(date.getMinutes()).padStart(2, "0");
  const s = String(date.getSeconds()).padStart(2, "0");
  return `${d} ${mon} ${y}, ${h}:${m}:${s}`;
}

export const RomMGameInfoPanel: FC<RomMGameInfoPanelProps> = ({ appId }) => {
  const [state, setState] = useState<PanelState>({
    loading: true,
    romId: null,
    romName: "",
    platformName: "",
    platformSlug: "",
    installed: false,
    installedRom: null,
    metadata: null,
    biosStatus: null,
    saveSyncEnabled: false,
    saveStatus: null,
    conflicts: [],
    error: false,
  });
  const [actionPending, setActionPending] = useState<string | null>(null);
  const romIdRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        const rom = await getRomBySteamAppId(appId);
        if (cancelled || !rom) {
          if (!cancelled) setState((prev) => ({ ...prev, loading: false, error: !rom }));
          return;
        }

        const romId: number = rom.rom_id;
        const romName: string = rom.name || "";
        const platformName: string = rom.platform_name || "";
        const platformSlug: string = rom.platform_slug || "";

        romIdRef.current = romId;

        // Fetch metadata, installed status, BIOS, save sync in parallel
        const [metadata, installedRom, biosResult, saveSyncSettings, saveStatus, conflictsResult] = await Promise.all([
          getRomMetadata(romId).catch((): RomMetadata | null => null),
          getInstalledRom(romId).catch((): InstalledRom | null => null),
          checkPlatformBios(platformSlug).catch((): BiosStatus => ({ needs_bios: false })),
          getSaveSyncSettings().catch((): SaveSyncSettings => ({
            save_sync_enabled: false,
            conflict_mode: "newest_wins",
            sync_before_launch: false,
            sync_after_exit: false,
            clock_skew_tolerance_sec: 60,
          })),
          getSaveStatus(romId).catch((): SaveStatus | null => null),
          getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
        ]);

        if (cancelled) return;

        setState({
          loading: false,
          romId,
          romName,
          platformName,
          platformSlug,
          installed: !!installedRom,
          installedRom,
          metadata,
          biosStatus: biosResult.needs_bios ? biosResult : null,
          saveSyncEnabled: saveSyncSettings.save_sync_enabled,
          saveStatus,
          conflicts: conflictsResult.conflicts.filter((c) => c.rom_id === romId),
          error: false,
        });
      } catch (e) {
        debugLog(`RomMGameInfoPanel: loadData error: ${e}`);
        if (!cancelled) setState((prev) => ({ ...prev, loading: false, error: true }));
      }
    }

    loadData();

    // Listen for uninstall events to update state (uses ref to avoid stale closure)
    const onUninstall = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.rom_id === romIdRef.current) {
        setState((prev) => ({ ...prev, installed: false, installedRom: null }));
      }
    };
    window.addEventListener("romm_rom_uninstalled", onUninstall);

    return () => {
      cancelled = true;
      window.removeEventListener("romm_rom_uninstalled", onUninstall);
    };
  }, [appId]);

  // --- Action handlers ---

  const handleRefreshArtwork = async () => {
    if (actionPending) return;
    setActionPending("artwork");
    try {
      // Fetch all three artwork types: 0=grid, 1=hero, 2=logo
      const results = await Promise.all([
        getSgdbArtworkBase64(appId, 0).catch(() => ({ base64: null, no_api_key: false })),
        getSgdbArtworkBase64(appId, 1).catch(() => ({ base64: null, no_api_key: false })),
        getSgdbArtworkBase64(appId, 2).catch(() => ({ base64: null, no_api_key: false })),
      ]);

      const anyNoKey = results.some((r) => r.no_api_key);
      if (anyNoKey) {
        toaster.toast({ title: "RomM Sync", body: "Set a SteamGridDB API key in settings first" });
      } else {
        const fetched = results.filter((r) => r.base64).length;
        toaster.toast({ title: "RomM Sync", body: `Artwork refreshed (${fetched}/3 images)` });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Failed to refresh artwork" });
    } finally {
      setActionPending(null);
    }
  };

  const handleRefreshMetadata = async () => {
    if (actionPending || !state.romId) return;
    setActionPending("metadata");
    try {
      const metadata = await getRomMetadata(state.romId);
      setState((prev) => ({ ...prev, metadata }));
      toaster.toast({ title: "RomM Sync", body: "Metadata refreshed" });
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Failed to refresh metadata" });
    } finally {
      setActionPending(null);
    }
  };

  const handleUninstall = async () => {
    if (actionPending || !state.romId) return;
    setActionPending("uninstall");
    try {
      const result = await removeRom(state.romId);
      if (result.success) {
        window.dispatchEvent(new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: state.romId } }));
        setState((prev) => ({ ...prev, installed: false, installedRom: null }));
        toaster.toast({ title: "RomM Sync", body: `${state.romName || "ROM"} uninstalled` });
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "Uninstall failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Uninstall failed" });
    } finally {
      setActionPending(null);
    }
  };

  const handleDownloadBios = async () => {
    if (actionPending || !state.platformSlug) return;
    setActionPending("bios");
    try {
      const result = await downloadAllFirmware(state.platformSlug);
      if (result.success) {
        toaster.toast({ title: "RomM Sync", body: `BIOS downloaded (${result.downloaded ?? 0} files)` });
        // Refresh BIOS status
        const updated = await checkPlatformBios(state.platformSlug).catch((): BiosStatus => ({ needs_bios: false }));
        setState((prev) => ({ ...prev, biosStatus: updated.needs_bios ? updated : null }));
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "BIOS download failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "BIOS download failed" });
    } finally {
      setActionPending(null);
    }
  };

  const handleSyncSaves = async () => {
    if (actionPending || !state.romId) return;
    setActionPending("savesync");
    try {
      const result = await syncRomSaves(state.romId);
      if (result.success) {
        toaster.toast({ title: "RomM Sync", body: `Saves synced (${result.synced} files)` });
        // Refresh save status
        const [updatedStatus, updatedConflicts] = await Promise.all([
          getSaveStatus(state.romId).catch((): SaveStatus | null => null),
          getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
        ]);
        setState((prev) => ({
          ...prev,
          saveStatus: updatedStatus,
          conflicts: updatedConflicts.conflicts.filter((c) => c.rom_id === state.romId),
        }));
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "Save sync failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Save sync failed" });
    } finally {
      setActionPending(null);
    }
  };

  // --- Render helpers ---

  /** A labeled info row: LABEL on the left, value on the right */
  const infoRow = (key: string, label: string, value: string) =>
    createElement("div", { key, className: "romm-panel-info-row" },
      createElement("span", { className: "romm-panel-label" }, label),
      createElement("span", { className: "romm-panel-value" }, value),
    );

  /** A section with a title and children */
  const section = (key: string, title: string | null, ...children: (ReturnType<typeof createElement> | null)[]) =>
    createElement("div", { key, className: "romm-panel-section" },
      title ? createElement("div", { className: "romm-panel-section-title" }, title) : null,
      ...children.filter(Boolean),
    );

  // --- Loading state ---
  if (state.loading) {
    return createElement("div", {
      "data-romm": "true",
      className: "romm-panel-container",
    },
      createElement("div", { className: "romm-panel-loading" }, "Loading..."),
    );
  }

  // --- Error / not found state ---
  if (state.error || !state.romId) {
    return null;
  }

  const meta = state.metadata;

  // --- Status Row ---
  const statusRow = createElement("div", {
    key: "status-row",
    className: "romm-panel-status-row",
  },
    createElement("span", {
      className: `romm-panel-status-badge ${state.installed ? "romm-panel-status-installed" : "romm-panel-status-not-installed"}`,
    }, state.installed ? "Downloaded" : "Not Installed"),
    state.platformName
      ? createElement("span", { className: "romm-panel-platform-badge" }, state.platformName)
      : null,
  );

  // --- Game Info section ---
  const gameInfoChildren: ReturnType<typeof createElement>[] = [];

  if (meta) {
    if (meta.summary) {
      gameInfoChildren.push(
        createElement("div", { key: "summary", className: "romm-panel-summary" }, meta.summary),
      );
    }

    if (meta.companies && meta.companies.length > 0) {
      gameInfoChildren.push(infoRow("companies", "Developer / Publisher", meta.companies.join(", ")));
    }

    if (meta.genres && meta.genres.length > 0) {
      gameInfoChildren.push(
        createElement("div", { key: "genres", className: "romm-panel-info-row" },
          createElement("span", { className: "romm-panel-label" }, "Genres"),
          createElement("div", { className: "romm-panel-tags" },
            ...meta.genres.map((g) =>
              createElement("span", { key: g, className: "romm-panel-tag" }, g),
            ),
          ),
        ),
      );
    }

    const releaseDate = formatReleaseDate(meta.first_release_date);
    if (releaseDate) {
      gameInfoChildren.push(infoRow("release-date", "Release Date", releaseDate));
    }

    if (meta.game_modes && meta.game_modes.length > 0) {
      gameInfoChildren.push(infoRow("game-modes", "Game Modes", meta.game_modes.join(", ")));
    }

    if (meta.player_count) {
      gameInfoChildren.push(infoRow("players", "Players", meta.player_count));
    }

    if (meta.average_rating != null && meta.average_rating > 0) {
      gameInfoChildren.push(infoRow("rating", "Rating", `${Math.round(meta.average_rating)}%`));
    }
  }

  const gameInfoSection = gameInfoChildren.length > 0
    ? section("game-info", "Game Info", ...gameInfoChildren)
    : section("game-info", "Game Info",
        createElement("div", { key: "no-meta", className: "romm-panel-muted" }, "No metadata available"),
      );

  // --- ROM File section (only when installed) ---
  const romFileSection = state.installed && state.installedRom
    ? section("rom-file", "ROM File",
        infoRow("filename", "Filename", state.installedRom.file_name),
      )
    : null;

  // --- BIOS section (only when platform needs BIOS) ---
  let biosSection: ReturnType<typeof createElement> | null = null;
  if (state.biosStatus) {
    const bios = state.biosStatus;
    const localCount = bios.local_count ?? 0;
    const serverCount = bios.server_count ?? 0;
    const biosColor = bios.all_downloaded ? "#5ba32b" : localCount > 0 ? "#d4a72c" : "#d94126";
    const biosLabel = bios.all_downloaded
      ? `All ready (${localCount}/${serverCount})`
      : `${localCount}/${serverCount} files ready`;

    const biosChildren: (ReturnType<typeof createElement> | null)[] = [];

    // Summary count + Download All button
    biosChildren.push(
      createElement("div", {
        key: "bios-row",
        className: "romm-panel-status-action-row",
      },
        createElement("div", {
          className: "romm-panel-status-inline",
        },
          createElement("span", {
            className: "romm-status-dot",
            style: { backgroundColor: biosColor },
          }),
          createElement("span", { className: "romm-panel-value" }, biosLabel),
        ),
        !bios.all_downloaded
          ? createElement(DialogButton, {
              key: "download-bios",
              className: "romm-panel-action-btn",
              style: { width: "auto", minWidth: 0, padding: "6px 14px" } as CSSProperties,
              onClick: handleDownloadBios,
              disabled: !!actionPending,
            }, actionPending === "bios" ? "Downloading..." : "Download All")
          : null,
      ),
    );

    // Individual file rows
    if (bios.files && bios.files.length > 0) {
      biosChildren.push(
        createElement("div", { key: "bios-file-list", className: "romm-panel-file-list" },
          ...bios.files.map((f) =>
            createElement("div", { key: f.file_name, className: "romm-panel-file-row" },
              createElement("span", {
                className: "romm-status-dot",
                style: { backgroundColor: f.downloaded ? "#5ba32b" : "#d94126" },
              }),
              createElement("span", { className: "romm-panel-file-name" }, f.file_name),
              createElement("span", { className: "romm-panel-file-path" }, f.local_path),
            ),
          ),
        ),
      );
    }

    biosSection = section("bios", "BIOS", ...biosChildren);
  }

  // --- Save Sync section (only when save sync enabled) ---
  let saveSyncSection: ReturnType<typeof createElement> | null = null;
  if (state.saveSyncEnabled) {
    const hasConflict = state.conflicts.length > 0;
    const fileCount = state.saveStatus?.files?.length ?? 0;

    let syncStatusLabel: string;
    let syncStatusColor: string;
    if (hasConflict) {
      syncStatusLabel = "Conflict detected";
      syncStatusColor = "#d94126";
    } else if (fileCount > 0) {
      const lastSync = state.saveStatus?.files
        ?.map((f) => f.last_sync_at)
        .filter(Boolean)
        .sort()
        .reverse()[0];
      if (lastSync) {
        const diffMs = Date.now() - new Date(lastSync).getTime();
        const diffMin = Math.floor(diffMs / 60000);
        if (diffMin < 1) syncStatusLabel = "Synced just now";
        else if (diffMin < 60) syncStatusLabel = `Synced ${diffMin}m ago`;
        else if (diffMin < 1440) syncStatusLabel = `Synced ${Math.floor(diffMin / 60)}h ago`;
        else syncStatusLabel = `Synced ${Math.floor(diffMin / 1440)}d ago`;
        syncStatusColor = "#5ba32b";
      } else {
        syncStatusLabel = "Not synced";
        syncStatusColor = "#8f98a0";
      }
    } else {
      syncStatusLabel = "No saves found";
      syncStatusColor = "#8f98a0";
    }

    const saveSyncChildren: (ReturnType<typeof createElement> | null)[] = [];

    // Status row with Sync Now button
    saveSyncChildren.push(
      createElement("div", {
        key: "savesync-status-row",
        className: "romm-panel-status-action-row",
      },
        createElement("div", {
          className: "romm-panel-status-inline",
        },
          createElement("span", {
            className: "romm-status-dot",
            style: { backgroundColor: syncStatusColor },
          }),
          createElement("span", { className: "romm-panel-value" }, syncStatusLabel),
        ),
        createElement(DialogButton, {
          key: "sync-now",
          className: "romm-panel-action-btn",
          style: { width: "auto", minWidth: 0, padding: "6px 14px" } as CSSProperties,
          onClick: handleSyncSaves,
          disabled: !!actionPending,
        }, actionPending === "savesync" ? "Syncing..." : "Sync Now"),
      ),
    );

    // File count subtitle
    if (fileCount > 0) {
      saveSyncChildren.push(
        createElement("div", {
          key: "savesync-count",
          className: "romm-panel-muted",
          style: { marginTop: "4px" },
        }, `${fileCount} save file${fileCount !== 1 ? "s" : ""} tracked`),
      );
    }

    // Individual save file rows
    if (state.saveStatus?.files && state.saveStatus.files.length > 0) {
      const handleResolveConflict = async (filename: string) => {
        if (actionPending || !state.romId) return;
        setActionPending("resolve");
        try {
          const result = await resolveConflict(state.romId, filename, "newest_wins");
          if (result.success) {
            toaster.toast({ title: "RomM Sync", body: `Conflict resolved for ${filename}` });
            // Refresh save status and conflicts
            const [updatedStatus, updatedConflicts] = await Promise.all([
              getSaveStatus(state.romId!).catch((): SaveStatus | null => null),
              getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
            ]);
            setState((prev) => ({
              ...prev,
              saveStatus: updatedStatus,
              conflicts: updatedConflicts.conflicts.filter((c) => c.rom_id === state.romId),
            }));
          } else {
            toaster.toast({ title: "RomM Sync", body: result.message || "Resolve failed" });
          }
        } catch {
          toaster.toast({ title: "RomM Sync", body: "Failed to resolve conflict" });
        } finally {
          setActionPending(null);
        }
      };

      saveSyncChildren.push(
        createElement("div", { key: "save-file-list", className: "romm-panel-file-list" },
          ...state.saveStatus.files.map((f) => {
            // Determine status dot color
            let dotColor: string;
            if (f.status === "conflict") {
              dotColor = "#d4a72c"; // orange for conflict
            } else if (f.status === "upload" || f.status === "download") {
              dotColor = "#d94126"; // red for pending
            } else if (f.last_sync_at) {
              dotColor = "#5ba32b"; // green for synced
            } else {
              dotColor = "#8f98a0"; // gray for no sync
            }

            const conflictForFile = state.conflicts.find((c) => c.filename === f.filename);
            const fileRowChildren: ReturnType<typeof createElement>[] = [];

            // Status dot + filename
            fileRowChildren.push(
              createElement("span", {
                key: "dot",
                className: "romm-status-dot",
                style: { backgroundColor: dotColor },
              }),
            );
            fileRowChildren.push(
              createElement("span", { key: "name", className: "romm-panel-file-name" }, f.filename),
            );

            // Sync datetime
            fileRowChildren.push(
              createElement("span", { key: "sync-time", className: "romm-panel-file-detail" },
                formatSyncDateTime(f.last_sync_at),
              ),
            );

            // Conflict label + resolve button
            if (f.status === "conflict" || conflictForFile) {
              fileRowChildren.push(
                createElement("span", { key: "conflict-label", className: "romm-panel-file-conflict" }, "Conflict"),
              );
              fileRowChildren.push(
                createElement(DialogButton, {
                  key: "resolve-btn",
                  className: "romm-panel-action-btn",
                  style: { width: "auto", minWidth: 0, padding: "3px 10px", fontSize: "11px" } as CSSProperties,
                  onClick: () => handleResolveConflict(f.filename),
                  disabled: !!actionPending,
                }, actionPending === "resolve" ? "..." : "Resolve"),
              );
            }

            // Local path on its own line (full width via flex-wrap)
            if (f.local_path) {
              fileRowChildren.push(
                createElement("span", {
                  key: "path",
                  className: "romm-panel-file-path",
                  style: { flexBasis: "100%" } as CSSProperties,
                }, f.local_path),
              );
            }

            return createElement("div", { key: f.filename, className: "romm-panel-file-row" },
              ...fileRowChildren,
            );
          }),
        ),
      );
    }

    saveSyncSection = section("save-sync", "Save Sync", ...saveSyncChildren);
  }

  // --- Actions section ---
  const actionButtons: ReturnType<typeof createElement>[] = [];

  const compactBtnStyle: CSSProperties = { width: "auto", minWidth: 0, padding: "6px 14px" };

  actionButtons.push(
    createElement(DialogButton, {
      key: "refresh-artwork",
      className: "romm-panel-action-btn",
      style: compactBtnStyle,
      onClick: handleRefreshArtwork,
      disabled: !!actionPending,
    }, actionPending === "artwork" ? "Refreshing..." : "Refresh Artwork"),
  );

  actionButtons.push(
    createElement(DialogButton, {
      key: "refresh-metadata",
      className: "romm-panel-action-btn",
      style: compactBtnStyle,
      onClick: handleRefreshMetadata,
      disabled: !!actionPending,
    }, actionPending === "metadata" ? "Refreshing..." : "Refresh Metadata"),
  );

  if (state.installed) {
    actionButtons.push(
      createElement(DialogButton, {
        key: "uninstall",
        className: "romm-panel-action-btn romm-panel-action-destructive",
        style: compactBtnStyle,
        onClick: handleUninstall,
        disabled: !!actionPending,
      }, actionPending === "uninstall" ? "Uninstalling..." : "Uninstall"),
    );
  }

  const actionsSection = section("actions", "Actions",
    createElement(Focusable, {
      key: "action-buttons",
      className: "romm-panel-actions-row",
      style: { display: "flex", gap: "8px", flexWrap: "wrap" } as CSSProperties,
      children: actionButtons,
    }),
  );

  // --- Assemble panel ---
  return createElement("div", {
    "data-romm": "true",
    className: "romm-panel-container",
  },
    statusRow,
    gameInfoSection,
    romFileSection,
    saveSyncSection,
    biosSection,
    actionsSection,
  );
};
