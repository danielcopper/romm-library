import { definePlugin, addEventListener, removeEventListener, toaster } from "@decky/api";
import { useState, FC } from "react";
import { PanelSection, PanelSectionRow, ButtonItem } from "@decky/ui";
import { FaGamepad } from "react-icons/fa";
import { Settings } from "./components/Settings";
import { DownloadQueue } from "./components/DownloadQueue";
import { createOrUpdateCollections } from "./utils/collections";

type Tab = "settings" | "downloads";

const QAMPanel: FC = () => {
  const [tab, setTab] = useState<Tab>("settings");

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => setTab("settings")}
            disabled={tab === "settings"}
          >
            Settings
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => setTab("downloads")}
            disabled={tab === "downloads"}
          >
            Downloads
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {tab === "settings" ? <Settings /> : <DownloadQueue />}
    </>
  );
};

export default definePlugin(() => {
  const onSyncComplete = (data: { platform_app_ids: Record<string, number[]>; total_games: number }) => {
    createOrUpdateCollections(data.platform_app_ids);
    toaster.toast({
      title: "RomM Library",
      body: `Sync complete! ${data.total_games} games added.`,
    });
  };

  const listener = addEventListener<[{ platform_app_ids: Record<string, number[]>; total_games: number }]>(
    "sync_complete",
    onSyncComplete
  );

  return {
    name: "RomM Library",
    icon: <FaGamepad />,
    content: <QAMPanel />,
    onDismount() {
      removeEventListener("sync_complete", listener);
    },
  };
});
