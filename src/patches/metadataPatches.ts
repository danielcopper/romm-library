import type { RomMetadata } from "../types";
import { debugLog, logInfo } from "../api/backend";

// Module-level state
let metadataCache: Record<string, RomMetadata> = {};
let appIdToRomId: Record<number, number> = {};
let registeredAppIds: Set<number> = new Set();

// Genre string → Steam StoreCategory ID mapping
const GENRE_CATEGORY_MAP: Record<string, number> = {
  "Action": 21,
  "Adventure": 25,
  "RPG": 21,
  "Role-playing (RPG)": 21,
  "Role-playing": 21,
  "Strategy": 2,
  "Simulation": 28,
  "Sport": 18,
  "Sports": 18,
  "Racing": 9,
  "Puzzle": 4,
};

// Game mode string → Steam StoreCategory ID mapping
const MODE_CATEGORY_MAP: Record<string, number> = {
  "Single player": 2,
  "Multiplayer": 1,
  "Co-operative": 9,
  "Split screen": 24,
  "MMO": 20,
};

/**
 * Wrap MobX state mutations so Steam's observable stores allow changes.
 */
function stateTransaction<T>(block: () => T): T {
  const globals = (window as any).__mobxGlobals;
  if (!globals) return block();
  const prev = globals.allowStateChanges;
  globals.allowStateChanges = true;
  try {
    return block();
  } finally {
    globals.allowStateChanges = prev;
  }
}

/**
 * Look up cached metadata for a given Steam app ID.
 */
function getMetadataForAppId(appId: number): RomMetadata | null {
  const romId = appIdToRomId[appId];
  if (romId == null) return null;
  return metadataCache[String(romId)] || null;
}

/**
 * Build the set of Steam category IDs from a ROM's genres and game modes.
 * Always includes category 28 (full controller support) for our games.
 */
function buildCategorySet(metadata: RomMetadata): Set<number> {
  const categories = new Set<number>();
  // Full controller support for all RomM games
  categories.add(28);

  for (const genre of metadata.genres) {
    const cat = GENRE_CATEGORY_MAP[genre];
    if (cat != null) categories.add(cat);
  }
  for (const mode of metadata.game_modes) {
    const cat = MODE_CATEGORY_MAP[mode];
    if (cat != null) categories.add(cat);
  }
  return categories;
}

/**
 * Apply direct property mutations to a SteamAppOverview for a RomM app.
 */
function applyDirectMutations(appId: number, metadata: RomMetadata) {
  const overview = appStore.GetAppOverviewByAppID(appId);
  if (!overview) return;

  stateTransaction(() => {
    // Full controller support
    overview.controller_support = 2;

    // Metacritic score from average_rating (0-100 scale, rounded)
    if (metadata.average_rating != null) {
      overview.metacritic_score = Math.round(metadata.average_rating);
    }

    // Add store categories
    if (overview.m_setStoreCategories) {
      const cats = buildCategorySet(metadata);
      for (const cat of cats) {
        overview.m_setStoreCategories.add(cat);
      }
    }
  });
}

/**
 * Initialize metadata state and apply direct property mutations.
 * Call on plugin load after fetching the metadata cache and app ID map.
 */
export function registerMetadataPatches(
  cache: Record<string, RomMetadata>,
  appIdMap: Record<string, number>,
) {
  metadataCache = cache;

  // Build reverse lookup: app_id → rom_id
  appIdToRomId = {};
  for (const [appIdStr, romId] of Object.entries(appIdMap)) {
    appIdToRomId[Number(appIdStr)] = romId;
  }

  // Build set of registered app IDs
  registeredAppIds = new Set(Object.keys(appIdToRomId).map(Number));

  // Apply direct mutations for all known apps (controller support, categories, metacritic)
  for (const appId of registeredAppIds) {
    const meta = getMetadataForAppId(appId);
    if (meta) applyDirectMutations(appId, meta);
  }

  logInfo(`Applied metadata mutations for ${registeredAppIds.size} apps`);
}

/**
 * Clean up metadata state. Call on plugin dismount.
 */
export function unregisterMetadataPatches() {
  metadataCache = {};
  appIdToRomId = {};
  registeredAppIds = new Set();
  logInfo("Cleared metadata state");
}

/**
 * Write tracked playtime to Steam's native UI fields.
 * Sets minutes_playtime_forever and rt_last_time_played so Steam shows
 * actual play time instead of "Never Played" for RomM shortcuts.
 * Returns true if the write succeeded, false if the overview wasn't available.
 */
export function updatePlaytimeDisplay(appId: number, totalSeconds: number): boolean {
  const overview = appStore.GetAppOverviewByAppID(appId);
  if (!overview) {
    debugLog(`updatePlaytimeDisplay: appId=${appId} overview=null, skipping`);
    return false;
  }

  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes <= 0) return true; // Nothing to write, but not a failure

  const prevMinutes = overview.minutes_playtime_forever;
  const prevLastPlayed = overview.rt_last_time_played;
  stateTransaction(() => {
    overview.minutes_playtime_forever = totalMinutes;
    overview.rt_last_time_played = Math.floor(Date.now() / 1000);
  });
  debugLog(`updatePlaytimeDisplay: appId=${appId} wrote ${totalMinutes}min (was ${prevMinutes}), rt_last_time_played was ${prevLastPlayed}`);
  return true;
}

/**
 * Apply playtime data for all known apps from the bulk playtime map.
 * Retries apps whose appStore overview isn't available yet (Steam may
 * still be loading shortcuts into its MobX store at plugin init).
 * Called at plugin load and after sync_complete.
 */
export async function applyAllPlaytime(
  playtimeMap: Record<string, { total_seconds: number }>,
  appIdMap: Record<string, number>,
) {
  // Build rom_id -> app_id reverse lookup
  const romIdToAppId: Record<string, number> = {};
  for (const [appIdStr, romId] of Object.entries(appIdMap)) {
    romIdToAppId[String(romId)] = Number(appIdStr);
  }

  // Build list of {appId, totalSeconds} to apply
  let pending: { appId: number; totalSeconds: number }[] = [];
  for (const [romIdStr, entry] of Object.entries(playtimeMap)) {
    const appId = romIdToAppId[romIdStr];
    if (appId && entry.total_seconds > 0) {
      pending.push({ appId, totalSeconds: entry.total_seconds });
    }
  }

  debugLog(`applyAllPlaytime: ${Object.keys(playtimeMap).length} entries in playtimeMap, ${pending.length} with appId and >0 seconds`);

  if (pending.length === 0) return;

  // Try up to 4 times with increasing delays (0ms, 1s, 3s, 5s)
  const delays = [0, 1000, 3000, 5000];
  for (let attempt = 0; attempt < delays.length && pending.length > 0; attempt++) {
    if (delays[attempt] > 0) {
      await new Promise((r) => setTimeout(r, delays[attempt]));
    }

    const failed: typeof pending = [];
    for (const item of pending) {
      if (!updatePlaytimeDisplay(item.appId, item.totalSeconds)) {
        failed.push(item);
      }
    }
    pending = failed;

    if (pending.length > 0 && attempt < delays.length - 1) {
      debugLog(`applyAllPlaytime: attempt ${attempt + 1}, ${pending.length} apps not in appStore yet, retrying in ${delays[attempt + 1]}ms...`);
    }
  }

  if (pending.length > 0) {
    debugLog(`applyAllPlaytime: ${pending.length} apps still unavailable in appStore after all retries`);
  }
}

/**
 * Update metadata cache for a single app and apply direct property mutations.
 * Called after fetching fresh metadata for a ROM.
 */
export function updateMetadataForApp(appId: number, romId: number, metadata: RomMetadata) {
  metadataCache[String(romId)] = metadata;
  appIdToRomId[appId] = romId;
  registeredAppIds.add(appId);
  applyDirectMutations(appId, metadata);
}

/**
 * Update the set of known RomM app IDs (e.g. after sync).
 */
export function setRegisteredAppIds(appIds: number[]) {
  registeredAppIds = new Set(appIds);
}

