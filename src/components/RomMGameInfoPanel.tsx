/**
 * RomMGameInfoPanel — metadata and actions panel injected below the PlaySection
 * on RomM game detail pages.
 *
 * Layout:
 *   Game Info:    Platform, Description, Developer/Publisher, Genre tags, Release date
 *   ROM File:     Filename (only when installed)
 *   BIOS:         Status (only when platform needs BIOS)
 *   Save Sync:    Status (only when save sync enabled)
 *   Purely informational — all actions live in RomMPlaySection gear menu.
 *
 * Uses createElement throughout (no JSX) to match the RomMPlaySection pattern.
 * CSS classes prefixed with `romm-panel-` are injected separately by styleInjector.
 */

import { useState, useEffect, useRef, FC, createElement } from "react";
import { DialogButton } from "@decky/ui";
// DialogButton is natively focusable by Steam's gamepad engine (unlike Focusable
// wrappers around non-interactive content, which don't register in this injection
// context). Style as content sections, not buttons.
import {
  getCachedGameDetail,
  getRomMetadata,
  getInstalledRom,
  checkPlatformBios,
  getSaveStatus,
  getPendingConflicts,
  getArtworkBase64,
  debugLog,
} from "../api/backend";
import type { RomMetadata, InstalledRom, BiosStatus, SaveStatus, PendingConflict } from "../types";
import { getMigrationState, onMigrationChange } from "../utils/migrationStore";

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
  coverBase64: string | null;
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
    coverBase64: null,
    biosStatus: null,
    saveSyncEnabled: false,
    saveStatus: null,
    conflicts: [],
    error: false,
  });
  const romIdRef = useRef<number | null>(null);
  const [migrationPending, setMigrationPending] = useState(getMigrationState().pending);

  useEffect(() => {
    const unsub = onMigrationChange(() => setMigrationPending(getMigrationState().pending));
    return unsub;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        // Phase 1: Cache-first — render instantly from cached data
        const cached = await getCachedGameDetail(appId);
        if (cancelled) return;
        if (!cached.found) {
          setState((prev) => ({ ...prev, loading: false, error: true }));
          return;
        }

        const romId = cached.rom_id!;
        const romName = cached.rom_name || "";
        const platformName = cached.platform_name || "";
        const platformSlug = cached.platform_slug || "";

        romIdRef.current = romId;

        // Build initial BIOS status from cache
        let biosStatus: BiosStatus | null = null;
        if (cached.bios_status) {
          biosStatus = {
            needs_bios: true,
            server_count: cached.bios_status.total,
            local_count: cached.bios_status.downloaded,
            all_downloaded: cached.bios_status.all_downloaded,
            required_count: cached.bios_status.required_count,
            required_downloaded: cached.bios_status.required_downloaded,
            files: cached.bios_status.files as BiosStatus["files"],
            active_core: cached.bios_status.active_core,
            active_core_label: cached.bios_status.active_core_label,
          };
        }

        // Build initial save status from cache
        let saveStatus: SaveStatus | null = null;
        if (cached.save_status) {
          saveStatus = {
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
        }

        // Build pending conflicts from cache
        const conflicts = (cached.pending_conflicts ?? [])
          .filter((c) => c.rom_id === romId)
          .map((c) => ({
            rom_id: c.rom_id,
            filename: c.filename,
            local_path: null,
            local_hash: null,
            local_mtime: null,
            local_size: null,
            server_save_id: 0,
            server_updated_at: "",
            server_size: null,
            created_at: c.detected_at,
          })) as PendingConflict[];

        // Render immediately with cached data (metadata may be null — that's OK)
        setState({
          loading: false,
          romId,
          romName,
          platformName,
          platformSlug,
          installed: cached.installed ?? false,
          installedRom: null, // Will be filled by background fetch if installed
          metadata: cached.metadata as RomMetadata | null,
          coverBase64: null, // Will be filled by background fetch
          biosStatus,
          saveSyncEnabled: cached.save_sync_enabled ?? false,
          saveStatus,
          conflicts,
          error: false,
        });

        // Phase 2: Background fetch for data not available in cache
        // (installed ROM details, cover art, full save/BIOS detail, metadata if missing)
        const bgPromises: Promise<void>[] = [];

        // Installed ROM details (for filename display)
        if (cached.installed) {
          bgPromises.push(
            getInstalledRom(romId).then((installed) => {
              if (!cancelled && installed) {
                setState((prev) => ({ ...prev, installedRom: installed }));
              }
            }).catch(() => {}),
          );
        }

        // Cover art
        bgPromises.push(
          getArtworkBase64(romId).then((result) => {
            if (!cancelled && result.base64) {
              setState((prev) => ({ ...prev, coverBase64: result.base64 }));
            }
          }).catch(() => {}),
        );

        // Metadata (if missing or stale >7 days)
        const METADATA_TTL_SEC = 7 * 24 * 3600;
        const metaCachedAt = (cached.metadata as Record<string, unknown> | null)?.cached_at as number | undefined;
        const metaStale = !metaCachedAt || (Date.now() / 1000 - metaCachedAt) > METADATA_TTL_SEC;
        if (!cached.metadata || metaStale) {
          bgPromises.push(
            getRomMetadata(romId).then((meta) => {
              if (!cancelled && meta) {
                setState((prev) => ({ ...prev, metadata: meta }));
              }
            }).catch(() => {}),
          );
        }

        await Promise.all(bgPromises);
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

    const onDataChanged = async (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!romIdRef.current) return;

      if (detail?.type === "save_sync_settings") {
        const enabled = detail.save_sync_enabled as boolean;
        if (enabled) {
          const [updatedStatus, updatedConflicts] = await Promise.all([
            getSaveStatus(romIdRef.current).catch((): SaveStatus | null => null),
            getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
          ]);
          setState((prev) => ({
            ...prev,
            saveSyncEnabled: true,
            saveStatus: updatedStatus,
            conflicts: updatedConflicts.conflicts.filter((c) => c.rom_id === romIdRef.current),
          }));
        } else {
          setState((prev) => ({ ...prev, saveSyncEnabled: false }));
        }
        return;
      }

      if (detail?.type === "save_sync" && (!detail.rom_id || detail.rom_id === romIdRef.current)) {
        const [updatedStatus, updatedConflicts] = await Promise.all([
          getSaveStatus(romIdRef.current).catch((): SaveStatus | null => null),
          getPendingConflicts().catch((): { conflicts: PendingConflict[] } => ({ conflicts: [] })),
        ]);
        setState((prev) => ({
          ...prev,
          saveStatus: updatedStatus,
          conflicts: updatedConflicts.conflicts.filter((c) => c.rom_id === romIdRef.current),
        }));
      } else if (detail?.type === "bios" && detail.platform_slug) {
        const updated = await checkPlatformBios(detail.platform_slug).catch((): BiosStatus => ({ needs_bios: false }));
        setState((prev) => ({ ...prev, biosStatus: updated.needs_bios ? updated : null }));
      } else if (detail?.type === "metadata" && detail.rom_id === romIdRef.current) {
        const meta = await getRomMetadata(romIdRef.current).catch((): RomMetadata | null => null);
        setState((prev) => ({ ...prev, metadata: meta }));
      }
    };
    window.addEventListener("romm_data_changed", onDataChanged);

    return () => {
      cancelled = true;
      window.removeEventListener("romm_rom_uninstalled", onUninstall);
      window.removeEventListener("romm_data_changed", onDataChanged);
    };
  }, [appId]);

  // Force Steam's scroll container to recalculate after content loads.
  // Double-RAF ensures the browser has painted the expanded content first.
  useEffect(() => {
    if (!state.loading && !state.error && state.romId) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.dispatchEvent(new Event("resize"));
        });
      });
    }
  }, [state.loading, state.error, state.romId]);

  // --- Render helpers ---

  /** A labeled info row: LABEL on the left, value on the right */
  const infoRow = (key: string, label: string, value: string) =>
    createElement("div", { key, className: "romm-panel-info-row" },
      createElement("span", { className: "romm-panel-label" }, label),
      createElement("span", { className: "romm-panel-value" }, value),
    );

  /** A section with a title and children — uses DialogButton (not Focusable)
   *  because DialogButton is natively focusable by Steam's gamepad engine.
   *  Styled to look like a content section, not a button.
   *  onFocus → scrollIntoView keeps the section visible when navigated to. */
  const section = (key: string, title: string | null, ...children: (ReturnType<typeof createElement> | null)[]) =>
    createElement(DialogButton as any, {
      key,
      className: "romm-panel-section",
      style: {
        background: "transparent",
        border: "none",
        padding: "12px 0",
        textAlign: "left" as const,
        width: "100%",
        cursor: "default",
        display: "block",
      },
      noFocusRing: false,
      onFocus: (e: FocusEvent) => {
        debugLog(`GameInfoPanel section "${key}" focused`);
        (e.currentTarget as HTMLElement)?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      },
    },
      title ? createElement("div", { className: "romm-panel-section-title" }, title) : null,
      ...children.filter(Boolean),
    );

  // --- Loading state ---
  // Use minHeight so Steam's scroll container allocates enough space
  // before async data loads and expands the panel.
  if (state.loading) {
    return createElement("div", {
      "data-romm": "true",
      className: "romm-panel-container",
      style: { minHeight: "500px" },
    },
      createElement("div", { className: "romm-panel-loading" }, "Loading..."),
    );
  }

  // --- Error / not found state ---
  if (state.error || !state.romId) {
    return null;
  }

  const meta = state.metadata;

  // --- Game Info section ---
  const gameInfoChildren: ReturnType<typeof createElement>[] = [];

  if (meta) {
    if (meta.summary) {
      gameInfoChildren.push(
        createElement("div", { key: "summary", className: "romm-panel-summary" }, meta.summary),
      );
    }

    // Platform after description
    if (state.platformName) {
      gameInfoChildren.push(infoRow("platform", "Platform", state.platformName));
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
  } else {
    // No metadata — still show platform
    if (state.platformName) {
      gameInfoChildren.push(infoRow("platform", "Platform", state.platformName));
    }
  }

  const gameInfoContent = gameInfoChildren.length > 0
    ? gameInfoChildren
    : [createElement("div", { key: "no-meta", className: "romm-panel-muted" }, "No metadata available")];

  const gameInfoSection = state.coverBase64
    ? section("game-info", "Game Info",
        createElement("div", {
          key: "game-info-row",
          style: { display: "flex", gap: "16px", alignItems: "flex-start" },
        },
          createElement("img", {
            key: "cover",
            src: `data:image/png;base64,${state.coverBase64}`,
            style: { width: "120px", borderRadius: "4px", flexShrink: 0, objectFit: "cover" as const },
          }),
          createElement("div", { key: "details", style: { flex: 1 } }, ...gameInfoContent),
        ),
      )
    : section("game-info", "Game Info", ...gameInfoContent);

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
    const reqCount = bios.required_count;
    const reqDone = bios.required_downloaded;

    let biosColor: string;
    let biosLabel: string;
    if (reqCount != null && reqDone != null) {
      biosColor = reqDone >= reqCount ? "#5ba32b" : reqDone > 0 ? "#d4a72c" : "#d94126";
      biosLabel = reqDone >= reqCount
        ? `All required ready (${localCount}/${serverCount})`
        : `${reqDone}/${reqCount} required files ready`;
    } else {
      biosColor = bios.all_downloaded ? "#5ba32b" : localCount > 0 ? "#d4a72c" : "#d94126";
      biosLabel = bios.all_downloaded
        ? `All ready (${localCount}/${serverCount})`
        : `${localCount}/${serverCount} files ready`;
    }

    const biosChildren: (ReturnType<typeof createElement> | null)[] = [];

    // Summary count
    biosChildren.push(
      createElement("div", {
        key: "bios-row",
        className: "romm-panel-status-inline",
      },
        createElement("span", {
          className: "romm-status-dot",
          style: { backgroundColor: biosColor },
        }),
        createElement("span", { className: "romm-panel-value" }, biosLabel),
      ),
    );

    // Active core label
    if (bios.active_core_label) {
      biosChildren.push(
        infoRow("core", "Core", bios.active_core_label)
      );
    }

    // Individual file rows
    if (bios.files && bios.files.length > 0) {
      biosChildren.push(
        createElement("div", { key: "bios-file-list", className: "romm-panel-file-list" },
          ...bios.files.map((f) => {
            let dotColor: string;
            if (f.classification === "unknown") {
              dotColor = "#d4a72c";
            } else if (f.downloaded) {
              dotColor = "#5ba32b";
            } else if (f.classification === "required") {
              dotColor = "#d94126";
            } else {
              dotColor = "#8f98a0";
            }
            return createElement("div", { key: f.file_name, className: "romm-panel-file-row" },
              createElement("span", {
                className: "romm-status-dot",
                style: { backgroundColor: dotColor },
              }),
              createElement("span", { className: "romm-panel-file-name" },
                `${f.description || f.file_name} (${f.classification})`,
              ),
              createElement("span", { className: "romm-panel-file-path" }, f.file_name !== (f.description || f.file_name) ? f.file_name : f.local_path),
            );
          }),
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
      const lastCheck = state.saveStatus?.last_sync_check_at;
      if (lastCheck) {
        const diffMs = Date.now() - new Date(lastCheck).getTime();
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

    // Status row
    saveSyncChildren.push(
      createElement("div", {
        key: "savesync-status-row",
        className: "romm-panel-status-inline",
      },
        createElement("span", {
          className: "romm-status-dot",
          style: { backgroundColor: syncStatusColor },
        }),
        createElement("span", { className: "romm-panel-value" }, syncStatusLabel),
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

            // Last synced datetime (use ROM-level check time — covers all files in the sync run)
            const syncTime = state.saveStatus?.last_sync_check_at || f.last_sync_at;
            fileRowChildren.push(
              createElement("span", { key: "sync-time", className: "romm-panel-file-detail" },
                `Synced: ${formatSyncDateTime(syncTime)}`,
              ),
            );

            // Last changed datetime (file modification time)
            if (f.local_mtime) {
              fileRowChildren.push(
                createElement("span", { key: "change-time", className: "romm-panel-file-detail" },
                  `Changed: ${formatSyncDateTime(f.local_mtime)}`,
                ),
              );
            }

            // Conflict label (informational only)
            if (f.status === "conflict" || conflictForFile) {
              fileRowChildren.push(
                createElement("span", { key: "conflict-label", className: "romm-panel-file-conflict" }, "Conflict"),
              );
            }

            // Local path on its own line (full width via flex-wrap)
            if (f.local_path) {
              fileRowChildren.push(
                createElement("span", {
                  key: "path",
                  className: "romm-panel-file-path",
                  style: { flexBasis: "100%" },
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

  // --- Migration warning (when path change pending) ---
  const migrationWarning = migrationPending
    ? createElement("div", {
        key: "migration-warning",
        style: {
          padding: "8px 12px",
          marginBottom: "12px",
          backgroundColor: "rgba(212, 167, 44, 0.15)",
          borderLeft: "3px solid #d4a72c",
          borderRadius: "4px",
        },
      },
        createElement("div", {
          style: { fontSize: "13px", fontWeight: "bold", color: "#d4a72c", marginBottom: "4px" },
        }, "\u26A0\uFE0F RetroDECK location changed"),
        createElement("div", {
          style: { fontSize: "12px", color: "rgba(255, 255, 255, 0.7)" },
        }, "File paths may be incorrect. Go to Settings to migrate files."),
      )
    : null;

  // --- Assemble panel ---
  // Root is a plain div — DialogButton sections inside are individually focusable.
  return createElement("div", {
    "data-romm": "true",
    className: "romm-panel-container",
    style: { paddingBottom: "48px" },
  },
    migrationWarning,
    gameInfoSection,
    romFileSection,
    saveSyncSection,
    biosSection,
  );
};
