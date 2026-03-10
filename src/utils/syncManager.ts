import { addEventListener } from "@decky/api";
import type { SyncApplyData, SyncChangedItem } from "../types";
import { getArtworkBase64, reportSyncResults, syncHeartbeat, logInfo, logError } from "../api/backend";
import { getExistingRomMShortcuts, addShortcut, removeShortcut } from "./steamShortcuts";
import { createOrUpdateCollections, clearPlatformCollection } from "./collections";
import { updateSyncProgress } from "./syncProgress";

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

let _cancelRequested = false;
let _isSyncRunning = false;

/** Request cancellation of the frontend shortcut processing loop. */
export function requestSyncCancel(): void {
  _cancelRequested = true;
}

/**
 * Initialize the sync manager that listens for sync_apply events from the backend.
 * Returns the event listener handle for cleanup.
 */
export function initSyncManager(): ReturnType<typeof addEventListener> {
  return addEventListener("sync_apply", async (data: SyncApplyData) => {
    if (_isSyncRunning) {
      logInfo("sync_apply: already running, ignoring duplicate event");
      return;
    }
    _isSyncRunning = true;
    try {
      // Defensive checks against malformed event data
      if (!Array.isArray(data.shortcuts)) {
        logError("sync_apply: data.shortcuts is not an array, aborting");
        return;
      }
      if (!Array.isArray(data.remove_rom_ids)) {
        logError("sync_apply: data.remove_rom_ids is not an array, aborting");
        return;
      }
      const isDelta = Array.isArray(data.changed_shortcuts);
      logInfo(`sync_apply received: ${data.shortcuts.length} new, ${isDelta ? data.changed_shortcuts!.length + " changed, " : ""}${data.remove_rom_ids.length} remove${isDelta ? " (delta)" : ""}`);
  
      _cancelRequested = false;
      let cancelled = false;
      let lastHeartbeat = Date.now();
      const HEARTBEAT_INTERVAL_MS = 10_000;
  
      const existing = await getExistingRomMShortcuts();
      const romIdToAppId: Record<string, number> = {};
      const removedRomIds: number[] = [];
      const artworkTargets: Array<{ appId: number; romId: number; name: string }> = [];
  
      // Step plan from backend
      let currentStep = data.next_step ?? 1;
      const totalSteps = data.total_steps ?? 3;
  
      // --- Step: Apply shortcuts (new + changed) ---
      const totalNew = data.shortcuts.length;
      const totalChanged = data.changed_shortcuts?.length ?? 0;
      const totalShortcuts = totalNew + totalChanged;
  
      if (totalShortcuts > 0) {
        updateSyncProgress({
          running: true, phase: "applying",
          current: 0, total: totalShortcuts,
          message: `Applying shortcuts 0/${totalShortcuts}`,
          step: currentStep, totalSteps,
        });
  
        for (let i = 0; i < data.shortcuts.length; i++) {
          const item = data.shortcuts[i];
          try {
            updateSyncProgress({
              current: i + 1,
              message: `Applying shortcuts ${i + 1}/${totalShortcuts}`,
            });
            let appId: number | undefined;
  
            if (isDelta) {
              const newAppId = await addShortcut(item);
              if (newAppId) {
                appId = newAppId;
                romIdToAppId[String(item.rom_id)] = newAppId;
              }
            } else {
              const existingAppId = existing.get(item.rom_id);
              if (existingAppId) {
                SteamClient.Apps.SetShortcutName(existingAppId, item.name);
                SteamClient.Apps.SetShortcutExe(existingAppId, item.exe);
                SteamClient.Apps.SetShortcutStartDir(existingAppId, item.start_dir);
                SteamClient.Apps.SetAppLaunchOptions(existingAppId, item.launch_options);
                appId = existingAppId;
                romIdToAppId[String(item.rom_id)] = existingAppId;
              } else {
                const newAppId = await addShortcut(item);
                if (newAppId) {
                  appId = newAppId;
                  romIdToAppId[String(item.rom_id)] = newAppId;
                }
              }
            }
  
            if (appId) {
              artworkTargets.push({ appId, romId: item.rom_id, name: item.name });
            }
          } catch (e) {
            logError(`Failed to process shortcut for rom ${item.rom_id}: ${e}`);
          }
          await delay(50);
  
          if (Date.now() - lastHeartbeat > HEARTBEAT_INTERVAL_MS) {
            syncHeartbeat().catch(() => {});
            lastHeartbeat = Date.now();
          }
  
          if (_cancelRequested) {
            logInfo(`Cancel requested after processing ${i + 1}/${totalShortcuts} shortcuts`);
            cancelled = true;
            break;
          }
        }
  
        // Process changed shortcuts (delta mode only)
        if (!cancelled && isDelta && data.changed_shortcuts) {
          for (let i = 0; i < data.changed_shortcuts.length; i++) {
            const item: SyncChangedItem = data.changed_shortcuts[i];
            const idx = totalNew + i;
            try {
              updateSyncProgress({
                current: idx + 1,
                message: `Updating shortcuts ${idx + 1}/${totalShortcuts}`,
              });
              const appId = item.existing_app_id;
  
              SteamClient.Apps.SetShortcutName(appId, item.name);
              SteamClient.Apps.SetShortcutExe(appId, item.exe);
              SteamClient.Apps.SetShortcutStartDir(appId, item.start_dir);
              SteamClient.Apps.SetAppLaunchOptions(appId, item.launch_options);
              romIdToAppId[String(item.rom_id)] = appId;
  
              artworkTargets.push({ appId, romId: item.rom_id, name: item.name });
            } catch (e) {
              logError(`Failed to update shortcut for rom ${item.rom_id}: ${e}`);
            }
            await delay(50);
  
            if (Date.now() - lastHeartbeat > HEARTBEAT_INTERVAL_MS) {
              syncHeartbeat().catch(() => {});
              lastHeartbeat = Date.now();
            }
  
            if (_cancelRequested) {
              logInfo(`Cancel requested during changed shortcuts processing`);
              cancelled = true;
              break;
            }
          }
        }
  
        currentStep++;
      }

      // --- Batch artwork fetch (parallel, up to 8 at a time) ---
      if (!cancelled && artworkTargets.length > 0) {
        const ART_CONCURRENCY = 8;
        for (let i = 0; i < artworkTargets.length; i += ART_CONCURRENCY) {
          if (_cancelRequested) {
            logInfo("Cancel requested during artwork fetching");
            cancelled = true;
            break;
          }
          const batch = artworkTargets.slice(i, i + ART_CONCURRENCY);
          await Promise.all(batch.map(async ({ appId, romId, name }) => {
            try {
              const artResult = await getArtworkBase64(romId);
              if (artResult.base64) {
                await SteamClient.Apps.SetCustomArtworkForApp(appId, artResult.base64, "png", 0);
                logInfo(`Set cover artwork for ${name} (appId=${appId})`);
              }
            } catch (artErr) {
              logError(`Failed to fetch/set artwork for ${name}: ${artErr}`);
            }
          }));
        }
      }

      // --- Step: Remove shortcuts ---
      if (!cancelled && data.remove_rom_ids.length > 0) {
        const totalRemovals = data.remove_rom_ids.length;
        updateSyncProgress({
          phase: "applying", current: 0, total: totalRemovals,
          message: `Removing shortcuts 0/${totalRemovals}`,
          step: currentStep, totalSteps,
        });
  
        for (let i = 0; i < data.remove_rom_ids.length; i++) {
          const romId = data.remove_rom_ids[i];
          const appId = existing.get(romId);
          if (appId) {
            removeShortcut(appId);
          }
          removedRomIds.push(romId);
          updateSyncProgress({
            current: i + 1,
            message: `Removing shortcuts ${i + 1}/${totalRemovals}`,
          });
          await delay(50);
  
          if (_cancelRequested) {
            logInfo("Cancel requested during removals");
            cancelled = true;
            break;
          }
        }
  
        currentStep++;
      }
  
      // Build platform app IDs for collections
      const platformAppIds: Record<string, number[]> = {};
      if (data.collection_platform_app_ids) {
        for (const [pname, appIds] of Object.entries(data.collection_platform_app_ids)) {
          platformAppIds[pname] = [...appIds];
        }
      }
      for (const item of data.shortcuts) {
        const appId = romIdToAppId[String(item.rom_id)];
        if (appId) {
          if (!platformAppIds[item.platform_name]) {
            platformAppIds[item.platform_name] = [];
          }
          platformAppIds[item.platform_name].push(appId);
        }
      }
      if (data.changed_shortcuts) {
        for (const item of data.changed_shortcuts) {
          const appId = romIdToAppId[String(item.rom_id)];
          if (appId) {
            if (!platformAppIds[item.platform_name]) {
              platformAppIds[item.platform_name] = [];
            }
            platformAppIds[item.platform_name].push(appId);
          }
        }
      }
  
      // --- Step: Update collections ---
      if (!cancelled && Object.keys(platformAppIds).length > 0) {
        const numCollections = Object.keys(platformAppIds).length;
        updateSyncProgress({
          phase: "applying", current: 0, total: numCollections,
          message: `Updating collections 0/${numCollections}`,
          step: currentStep, totalSteps,
        });
        await createOrUpdateCollections(platformAppIds, (cur, colTotal, _name) => {
          updateSyncProgress({
            current: cur, total: colTotal,
            message: `Updating collections ${cur}/${colTotal}`,
          });
        });
      }
  
      // Clean up stale collections
      if (!cancelled && typeof collectionStore !== "undefined") {
        const activePlatforms = new Set(Object.keys(platformAppIds));
        const staleCollections = collectionStore.userCollections.filter((c) => {
          if (!c.displayName.startsWith("RomM: ")) return false;
          const afterPrefix = c.displayName.slice(6);
          const platformName = afterPrefix.replace(/\s\([^)]+\)$/, "");
          return !activePlatforms.has(platformName);
        });
        for (const c of staleCollections) {
          const afterPrefix = c.displayName.slice(6);
          const platformName = afterPrefix.replace(/\s\([^)]+\)$/, "");
          logInfo(`Removing stale collection "${c.displayName}"`);
          await clearPlatformCollection(platformName);
        }
      }
  
      // Report results to backend
      try {
        await reportSyncResults(romIdToAppId, removedRomIds, cancelled);
      } catch (e) {
        logError(`Failed to report sync results: ${e}`);
      }
  
      const doneMsg = cancelled
        ? `Sync cancelled (${Object.keys(romIdToAppId).length} processed)`
        : "Sync complete";
      updateSyncProgress({ running: false, phase: "done", message: doneMsg });
      logInfo(`sync_apply ${cancelled ? "cancelled" : "complete"}: ${Object.keys(romIdToAppId).length} added/updated, ${removedRomIds.length} removed`);
    } finally {
      _isSyncRunning = false;
    }
  });
}
