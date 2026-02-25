/**
 * Custom Play button that replaces the native Steam Play button on RomM game
 * detail pages. Handles 3 primary states:
 * - Download: ROM not installed, click to download
 * - Play: ROM installed, launches the game (with pre-launch save sync)
 * - Syncing: Save sync in progress before launch
 *
 * Includes a dropdown menu button (arrow) to the right of the Play button
 * with action: Uninstall.
 */

import { useState, useEffect, useRef, FC } from "react";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import {
  Focusable,
  DialogButton,
  ConfirmModal,
  Menu,
  MenuItem,
  showContextMenu,
  showModal,
  appActionButtonClasses,
  basicAppDetailsSectionStylerClasses,
} from "@decky/ui";
import { hideNativePlaySection, showNativePlaySection } from "../utils/styleInjector";
import {
  getCachedGameDetail,
  startDownload,
  removeRom,
  debugLog,
  preLaunchSync,
  logError,
} from "../api/backend";
import { getRommConnectionState } from "../utils/connectionState";
import { showConflictResolutionModal } from "./ConflictModal";
import type { DownloadProgressEvent, DownloadCompleteEvent } from "../types";

type PlayButtonState = "loading" | "not_romm" | "download" | "conflict" | "syncing" | "play" | "launching";

interface CustomPlayButtonProps {
  appId: number;
}

function showLaunchConfirmation(title: string, message: string): Promise<boolean> {
  return new Promise((resolve) => {
    showModal(
      <ConfirmModal
        strTitle={title}
        strDescription={message}
        strOKButtonText="Launch Anyway"
        strCancelButtonText="Cancel"
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    );
  });
}

export const CustomPlayButton: FC<CustomPlayButtonProps> = ({ appId }) => {
  const [state, setState] = useState<PlayButtonState>("loading");
  const [romId, setRomId] = useState<number | null>(null);
  const [romName, setRomName] = useState<string>("");
  const [actionPending, setActionPending] = useState(false);
  const [isOffline, setIsOffline] = useState(getRommConnectionState() === "offline");
  const romIdRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Hide the native PlaySection via CSS while this component is mounted
  useEffect(() => {
    const cls = basicAppDetailsSectionStylerClasses?.PlaySection;
    if (cls) hideNativePlaySection(cls);
    return () => { showNativePlaySection(); };
  }, []);

  // Initial load: determine ROM status from cache (instant, no network calls)
  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        const cached = await getCachedGameDetail(appId);
        debugLog(`CustomPlayButton init: appId=${appId} cached.found=${cached.found} cancelled=${cancelled}`);
        if (cancelled) return;
        if (!cached.found) {
          debugLog(`CustomPlayButton: -> not_romm (not in cache)`);
          setState("not_romm");
          return;
        }

        const rid = cached.rom_id!;
        setRomId(rid);
        romIdRef.current = rid;
        if (cached.rom_name) setRomName(cached.rom_name);

        if (!cached.installed) {
          debugLog(`CustomPlayButton: -> download`);
          setState("download");
        } else {
          // Check for conflicts from cached save status
          const hasConflict = cached.save_status?.files?.some((f) => f.status === "conflict") ?? false;
          if (hasConflict) {
            debugLog(`CustomPlayButton: -> conflict (from cache)`);
            setState("conflict");
          } else {
            debugLog(`CustomPlayButton: -> play`);
            setState("play");
          }
        }
      } catch (e) {
        logError(`CustomPlayButton init error: ${e}`);
        if (!cancelled) {
          setState("not_romm");
        }
      }
    }

    init();
    return () => { cancelled = true; };
  }, [appId]);

  // Listen for download events
  useEffect(() => {
    const progressListener = addEventListener<[DownloadProgressEvent]>(
      "download_progress",
      (evt: DownloadProgressEvent) => {
        if (evt.rom_id !== romIdRef.current) return;
        if (evt.status === "failed" || evt.status === "cancelled") {
          setState("download");
          setActionPending(false);
        }
      },
    );

    const completeListener = addEventListener<[DownloadCompleteEvent]>(
      "download_complete",
      (evt: DownloadCompleteEvent) => {
        if (evt.rom_id !== romIdRef.current) return;
        setState("play");
        setActionPending(false);
      },
    );

    const onUninstall = (e: Event) => {
      const romId = (e as CustomEvent).detail?.rom_id;
      if (romId !== romIdRef.current) return;
      setState("download");
      setActionPending(false);
    };
    window.addEventListener("romm_rom_uninstalled", onUninstall);

    // Listen for save sync updates (e.g. lightweight background check found a conflict)
    const onDataChanged = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.type !== "save_sync") return;
      if (detail.rom_id && detail.rom_id !== romIdRef.current) return;
      // Update button state based on conflict info from the event
      if (detail.has_conflict !== undefined) {
        setState((prev) => {
          if (prev === "syncing" || prev === "launching" || prev === "download") return prev;
          return detail.has_conflict ? "conflict" : "play";
        });
      }
    };
    window.addEventListener("romm_data_changed", onDataChanged);

    const onConnectionChanged = (e: Event) => {
      const connState = (e as CustomEvent).detail?.state;
      setIsOffline(connState === "offline");
    };
    window.addEventListener("romm_connection_changed", onConnectionChanged);

    return () => {
      removeEventListener("download_progress", progressListener);
      removeEventListener("download_complete", completeListener);
      window.removeEventListener("romm_rom_uninstalled", onUninstall);
      window.removeEventListener("romm_data_changed", onDataChanged);
      window.removeEventListener("romm_connection_changed", onConnectionChanged);
    };
  }, []);

  // Programmatically focus our Play/Download button after mount.
  // This beats HLTB and other plugins that also compete for initial focus.
  useEffect(() => {
    if (state !== "play" && state !== "download" && state !== "conflict") return;
    const timer = setTimeout(() => {
      if (containerRef.current) {
        const btn = containerRef.current.querySelector("button");
        if (btn) {
          btn.focus();
          btn.classList.add("gpfocus");
        }
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [state]);

  const handlePlay = async () => {
    if (state === "syncing" || state === "launching") return; // debounce
    const overview = appStore.GetAppOverviewByAppID(appId);
    const gameId = overview?.GetGameID?.() ?? String(appId);
    debugLog(`CustomPlayButton: handlePlay appId=${appId} gameId=${gameId}`);

    // Pre-launch save sync
    if (romId) {
      if (getRommConnectionState() === "offline") {
        // RomM offline — warn user, skip sync attempt entirely
        const proceed = await showLaunchConfirmation(
          "RomM Offline",
          "Can't sync saves — RomM server is unreachable. Launch with local saves? Saves will sync after exit when the server is back, but may produce conflicts.",
        );
        if (!proceed) {
          setState("play");
          return;
        }
      } else {
        setState("syncing");
        try {
          const result = await Promise.race([
            preLaunchSync(romId),
            new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 15000)),
          ]);

          debugLog(`CustomPlayButton: preLaunchSync result: synced=${result.synced} conflicts=${result.conflicts?.length ?? 0} success=${result.success}`);

          if (result.conflicts && result.conflicts.length > 0) {
            const resolution = await showConflictResolutionModal(result.conflicts);
            if (resolution === "cancel") {
              setState("conflict");
              return;
            }
            // Conflict resolved — notify sibling components to refresh
            window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "save_sync", rom_id: romId } }));
          }

          if (!result.success && result.errors && result.errors.length > 0) {
            debugLog(`CustomPlayButton: pre-launch sync errors: ${result.errors.join(", ")}`);
            const proceed = await showLaunchConfirmation(
              "Save Sync Unavailable",
              "Couldn't sync saves with RomM server. Launch with local saves?",
            );
            if (!proceed) {
              setState("play");
              return;
            }
          } else if (result.synced && result.synced > 0) {
            toaster.toast({ title: "RomM Save Sync", body: "Saves downloaded from RomM" });
          }
        } catch (e) {
          debugLog(`CustomPlayButton: pre-launch sync failed: ${e}`);
          const proceed = await showLaunchConfirmation(
            "Save Sync Unavailable",
            "Couldn't sync saves with RomM server. Launch with local saves?",
          );
          if (!proceed) {
            setState("play");
            return;
          }
        }
      }
    }

    setState("launching");
    SteamClient.Apps.RunGame(gameId, "", -1, 100);
  };

  const handleResolveConflict = async () => {
    if (!romId) return;
    setState("syncing");
    try {
      const result = await Promise.race([
        preLaunchSync(romId),
        new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timeout")), 15000)),
      ]);

      if (result.conflicts && result.conflicts.length > 0) {
        const resolution = await showConflictResolutionModal(result.conflicts);
        if (resolution === "cancel") {
          setState("conflict");
          return;
        }
      }
      // Resolved or no conflicts left — notify siblings and go back to play
      window.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "save_sync", rom_id: romId } }));
      setState("play");
    } catch (e) {
      debugLog(`CustomPlayButton: resolve conflict failed: ${e}`);
      toaster.toast({ title: "RomM Sync", body: "Couldn't reach server to resolve conflict" });
      setState("conflict");
    }
  };

  const handleDownload = async () => {
    if (!romId || actionPending) return;
    setActionPending(true);
    try {
      const result = await startDownload(romId);
      if (!result.success) {
        toaster.toast({ title: "RomM Sync", body: result.message || "Download failed" });
        setActionPending(false);
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Download failed — is RomM server running?" });
      setActionPending(false);
    }
  };

  const handleUninstall = async () => {
    if (!romId) return;
    debugLog(`CustomPlayButton: uninstalling romId=${romId}`);
    try {
      const result = await removeRom(romId);
      if (result.success) {
        window.dispatchEvent(new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: romId } }));
        toaster.toast({ title: "RomM Sync", body: `${romName || "ROM"} uninstalled` });
      } else {
        toaster.toast({ title: "RomM Sync", body: result.message || "Uninstall failed" });
      }
    } catch {
      toaster.toast({ title: "RomM Sync", body: "Uninstall failed" });
    }
  };

  const showDropdownMenu = (e: MouseEvent) => {
    showContextMenu(
      <Menu label="RomM Actions">
        <MenuItem key="uninstall" tone="destructive" onClick={handleUninstall}>
          Uninstall
        </MenuItem>
      </Menu>,
      e.currentTarget as EventTarget,
    );
  };

  // Don't render for non-RomM games
  if (state === "not_romm" || state === "loading") {
    debugLog(`CustomPlayButton: returning null (state=${state})`);
    return null;
  }
  debugLog(`CustomPlayButton: rendering state=${state}`);

  // Dropdown arrow button style
  const dropdownArrowStyle: React.CSSProperties = {
    height: "48px",
    width: "36px",
    minWidth: "36px",
    padding: 0,
    border: "none",
    borderRadius: "0 2px 2px 0",
    cursor: "pointer",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderLeft: "1px solid rgba(0, 0, 0, 0.2)",
  };

  // Consistent button container size across all states (Play has dropdown = 36px extra)
  const btnContainerStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "row",
    width: "200px",
    height: "48px",
  };

  const mainBtnStyle: React.CSSProperties = {
    height: "100%",
    flex: "1 1 auto",
    padding: "4px 12px",
    border: "none",
    color: "#fff",
    fontSize: "16px",
    fontWeight: "bold",
  };

  if (state === "download") {
    return (
      <Focusable
        ref={containerRef}
        className={appActionButtonClasses?.PlayButtonContainer}
        style={btnContainerStyle}
      >
        <DialogButton
          className={[appActionButtonClasses?.PlayButton, "romm-btn-download"].filter(Boolean).join(" ")}
          style={{
            ...mainBtnStyle,
            borderRadius: "2px",
            background: "linear-gradient(to right, #1a9fff, #0078d4)",
          }}
          onClick={handleDownload}
          disabled={actionPending}
        >
          {actionPending ? "Downloading..." : "Download"}
        </DialogButton>
      </Focusable>
    );
  }

  if (state === "launching") {
    return (
      <Focusable
        className={appActionButtonClasses?.PlayButtonContainer}
        style={btnContainerStyle}
      >
        <DialogButton
          className={[appActionButtonClasses?.PlayButton, "romm-btn-play", isOffline && "romm-offline"].filter(Boolean).join(" ")}
          style={{
            ...mainBtnStyle,
            borderRadius: "2px",
            background: "linear-gradient(to right, #70d61d 0%, #01a75b 60%)",
            backgroundPosition: "25%",
            backgroundSize: "330% 100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
          }}
          disabled
        >
          <span className={`${appActionButtonClasses?.Throbber || ""} romm-throbber`.trim()} />
          Launching...
        </DialogButton>
      </Focusable>
    );
  }

  if (state === "syncing") {
    return (
      <Focusable
        className={appActionButtonClasses?.PlayButtonContainer}
        style={btnContainerStyle}
      >
        <DialogButton
          className={[appActionButtonClasses?.PlayButton, "romm-btn-play", isOffline && "romm-offline"].filter(Boolean).join(" ")}
          style={{
            ...mainBtnStyle,
            borderRadius: "2px",
            background: "linear-gradient(to right, #70d61d 0%, #01a75b 60%)",
            backgroundPosition: "25%",
            backgroundSize: "330% 100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
          }}
          disabled
        >
          <span className={`${appActionButtonClasses?.Throbber || ""} romm-throbber`.trim()} />
          Syncing saves...
        </DialogButton>
      </Focusable>
    );
  }

  if (state === "conflict") {
    return (
      <Focusable
        ref={containerRef}
        className={appActionButtonClasses?.PlayButtonContainer}
        style={btnContainerStyle}
      >
        <DialogButton
          className={[appActionButtonClasses?.PlayButton, "romm-btn-conflict"].filter(Boolean).join(" ")}
          style={{
            ...mainBtnStyle,
            borderRadius: "2px",
            background: "linear-gradient(to right, #d4a72c, #b8941f)",
          }}
          onClick={handleResolveConflict}
        >
          Resolve Conflict
        </DialogButton>
      </Focusable>
    );
  }

  // state === "play"
  const playBg = isOffline
    ? "linear-gradient(to right, #6b7b6b 0%, #5a6a5a 60%)"
    : "linear-gradient(to right, #70d61d 0%, #01a75b 60%)";
  const dropdownBg = isOffline
    ? "linear-gradient(to right, #5a6a5a, #4d5d4d)"
    : "linear-gradient(to right, #4da636, #3f8a2b)";
  return (
    <Focusable
      ref={containerRef}
      className={[appActionButtonClasses?.PlayButtonContainer, !isOffline && appActionButtonClasses?.Green].filter(Boolean).join(" ")}
      style={btnContainerStyle}
    >
      <DialogButton
        className={[appActionButtonClasses?.PlayButton, "romm-btn-play", isOffline && "romm-offline"].filter(Boolean).join(" ")}
        style={{
          ...mainBtnStyle,
          borderRadius: "2px 0 0 2px",
          background: playBg,
          backgroundPosition: "25%",
          backgroundSize: "330% 100%",
        }}
        onClick={handlePlay}
      >
        Play
      </DialogButton>
      <DialogButton
        className="romm-btn-dropdown"
        style={{
          ...dropdownArrowStyle,
          background: dropdownBg,
        }}
        onClick={showDropdownMenu}
      >
        <svg width="12" height="8" viewBox="0 0 12 8" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 1.5L6 6.5L11 1.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </DialogButton>
    </Focusable>
  );
};
