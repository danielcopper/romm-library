/**
 * Steam collection management for RomM platforms.
 * Uses Steam's internal collectionStore API if available.
 */

interface SteamCollection {
  AsDragDropCollection: () => unknown;
  bIsDynamic: boolean;
  displayName: string;
  id: string;
  visibleApps: Set<number>;
}

declare const collectionStore: {
  userCollections: SteamCollection[];
  CreateCollection: (name: string, apps?: number[]) => void;
  SetAppsInCollection: (id: string, apps: number[]) => void;
  GetCollection: (id: string) => SteamCollection | undefined;
} | undefined;

export function createOrUpdateCollections(
  platformAppIds: Record<string, number[]>
): void {
  try {
    if (typeof collectionStore === "undefined") {
      console.warn("[RomM] collectionStore not available, skipping collections");
      return;
    }

    for (const [platformName, appIds] of Object.entries(platformAppIds)) {
      const collectionName = `RomM: ${platformName}`;

      const existing = collectionStore.userCollections.find(
        (c) => c.displayName === collectionName
      );

      if (existing) {
        collectionStore.SetAppsInCollection(existing.id, appIds);
      } else {
        collectionStore.CreateCollection(collectionName, appIds);
      }
    }
  } catch (e) {
    console.error("[RomM] Failed to update collections:", e);
  }
}

export function clearPlatformCollection(platformName: string): void {
  try {
    if (typeof collectionStore === "undefined") return;
    const collectionName = `RomM: ${platformName}`;
    const existing = collectionStore.userCollections.find(
      (c) => c.displayName === collectionName
    );
    if (existing) {
      collectionStore.SetAppsInCollection(existing.id, []);
    }
  } catch (e) {
    console.error("[RomM] Failed to clear platform collection:", e);
  }
}

export function clearAllRomMCollections(): void {
  try {
    if (typeof collectionStore === "undefined") return;
    for (const c of collectionStore.userCollections) {
      if (c.displayName.startsWith("RomM: ")) {
        collectionStore.SetAppsInCollection(c.id, []);
      }
    }
  } catch (e) {
    console.error("[RomM] Failed to clear collections:", e);
  }
}
