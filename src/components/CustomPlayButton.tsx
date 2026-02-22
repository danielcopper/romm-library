/**
 * Custom Play button that replaces the native Steam Play button on RomM game
 * detail pages. Handles 2 primary states:
 * - Download: ROM not installed, click to download
 * - Play: ROM installed, launches the game
 *
 * Includes a dropdown menu button (arrow) to the right of the Play button
 * with action: Uninstall.
 */

import { useState, useEffect, useRef, FC } from "react";
import { addEventListener, removeEventListener, toaster } from "@decky/api";
import {
  Focusable,
  DialogButton,
  Menu,
  MenuItem,
  showContextMenu,
  appActionButtonClasses,
  basicAppDetailsSectionStylerClasses,
} from "@decky/ui";
import { hideNativePlaySection, showNativePlaySection } from "../utils/styleInjector";
import {
  getRomBySteamAppId,
  getInstalledRom,
  startDownload,
  removeRom,
  debugLog,
  getSaveSyncSettings,
  getPendingConflicts,
} from "../api/backend";
import type { DownloadProgressEvent, DownloadCompleteEvent, SaveSyncSettings, PendingConflict } from "../types";

type PlayButtonState = "loading" | "not_romm" | "download" | "conflict" | "play" | "launching";

interface CustomPlayButtonProps {
  appId: number;
}

export const CustomPlayButton: FC<CustomPlayButtonProps> = ({ appId }) => {
  debugLog(`CustomPlayButton: mounted appId=${appId}`);
  const [state, setState] = useState<PlayButtonState>("loading");
  const [romId, setRomId] = useState<number | null>(null);
  const [romName, setRomName] = useState<string>("");
  const [actionPending, setActionPending] = useState(false);
  const romIdRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Hide the native PlaySection via CSS while this component is mounted
  useEffect(() => {
    const cls = basicAppDetailsSectionStylerClasses?.PlaySection;
    if (cls) hideNativePlaySection(cls);
    return () => { showNativePlaySection(); };
  }, []);

  // Initial load: determine ROM status
  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        const rom = await getRomBySteamAppId(appId);
        debugLog(`CustomPlayButton init: appId=${appId} rom=${JSON.stringify(rom)} cancelled=${cancelled}`);
        if (cancelled) return;
        if (!rom) {
          debugLog(`CustomPlayButton: -> not_romm (no rom found)`);
          setState("not_romm");
          return;
        }

        setRomId(rom.rom_id);
        romIdRef.current = rom.rom_id;
        if (rom.name) setRomName(rom.name);

        const installed = await getInstalledRom(rom.rom_id);
        debugLog(`CustomPlayButton: romId=${rom.rom_id} installed=${!!installed}`);
        if (cancelled) return;

        if (!installed) {
          debugLog(`CustomPlayButton: -> download`);
          setState("download");
        } else {
          // Check for save sync conflicts before allowing play
          try {
            const settings: SaveSyncSettings = await getSaveSyncSettings();
            if (settings.save_sync_enabled) {
              const { conflicts }: { conflicts: PendingConflict[] } = await getPendingConflicts();
              const hasConflict = conflicts.some((c: PendingConflict) => c.rom_id === rom.rom_id);
              if (hasConflict) {
                debugLog(`CustomPlayButton: -> conflict (rom_id=${rom.rom_id})`);
                if (!cancelled) setState("conflict");
                return;
              }
            }
          } catch (e) {
            debugLog(`CustomPlayButton: conflict check failed, proceeding to play: ${e}`);
          }
          debugLog(`CustomPlayButton: -> play`);
          setState("play");
        }
      } catch (e) {
        console.error("[RomM] CustomPlayButton init error:", e);
        if (!cancelled) {
          setState("not_romm");
          toaster.toast({ title: "RomM Sync", body: "Could not connect to RomM server" });
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

    return () => {
      removeEventListener("download_progress", progressListener);
      removeEventListener("download_complete", completeListener);
      window.removeEventListener("romm_rom_uninstalled", onUninstall);
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

  const handlePlay = () => {
    const overview = appStore.GetAppOverviewByAppID(appId);
    const gameId = overview?.GetGameID?.() ?? String(appId);
    debugLog(`CustomPlayButton: handlePlay appId=${appId} gameId=${gameId}`);
    setState("launching");
    SteamClient.Apps.RunGame(gameId, "", -1, 100);
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
          className={[appActionButtonClasses?.PlayButton, "romm-btn-play"].filter(Boolean).join(" ")}
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
          onClick={() => {
            toaster.toast({ title: "RomM Sync", body: "Resolve save conflict in RomM Sync settings" });
          }}
        >
          Resolve Conflict
        </DialogButton>
      </Focusable>
    );
  }

  // state === "play"
  return (
    <Focusable
      ref={containerRef}
      className={[appActionButtonClasses?.PlayButtonContainer, appActionButtonClasses?.Green].filter(Boolean).join(" ")}
      style={btnContainerStyle}
    >
      <DialogButton
        className={[appActionButtonClasses?.PlayButton, "romm-btn-play"].filter(Boolean).join(" ")}
        style={{
          ...mainBtnStyle,
          borderRadius: "2px 0 0 2px",
          background: "linear-gradient(to right, #70d61d 0%, #01a75b 60%)",
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
          background: "linear-gradient(to right, #4da636, #3f8a2b)",
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
