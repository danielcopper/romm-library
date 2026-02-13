declare var SteamClient: {
  Apps: {
    AddShortcut(
      appName: string,
      exePath: string,
      startDir: string,
      launchArgs: string,
    ): Promise<number>;
    RemoveShortcut(appId: number): void;
    SetShortcutName(appId: number, name: string): void;
    SetShortcutExe(appId: number, exePath: string): void;
    SetShortcutStartDir(appId: number, startDir: string): void;
    SetAppLaunchOptions(appId: number, options: string): void;
    SetCustomArtworkForApp(
      appId: number,
      base64Data: string,
      imageType: "jpg" | "png",
      assetType: number,
    ): Promise<void>;
    ClearCustomArtworkForApp(appId: number, assetType: number): Promise<void>;
    RegisterForAppDetails(
      appId: number,
      callback: (details: any) => void,
    ): { unregister: () => void };
  };
};

declare var collectionStore: {
  deckDesktopApps: { apps: Map<number, any> };
  userCollections: any[];
  CreateCollection: (name: string, apps?: number[]) => void;
  SetAppsInCollection: (id: string, apps: number[]) => void;
  GetCollection: (id: string) => any | undefined;
};
