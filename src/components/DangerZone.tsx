import { useState, useEffect, FC } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  showModal,
  ConfirmModal,
  Spinner,
} from "@decky/ui";
import {
  getRegistryPlatforms,
  removePlatformShortcuts,
  removeAllShortcuts,
  reportRemovalResults,
} from "../api/backend";
import { removeShortcut } from "../utils/steamShortcuts";
import { clearPlatformCollection, clearAllRomMCollections } from "../utils/collections";
import type { RegistryPlatform } from "../types";

interface DangerZoneProps {
  onBack: () => void;
}

export const DangerZone: FC<DangerZoneProps> = ({ onBack }) => {
  const [status, setStatus] = useState("");
  const [platforms, setPlatforms] = useState<RegistryPlatform[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshPlatforms = async () => {
    setLoading(true);
    try {
      const result = await getRegistryPlatforms();
      setPlatforms(result.platforms || []);
    } catch {
      setPlatforms([]);
    }
    setLoading(false);
  };

  useEffect(() => {
    refreshPlatforms();
  }, []);

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onBack}>
            Back
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Remove by Platform">
        {loading ? (
          <PanelSectionRow>
            <Spinner />
          </PanelSectionRow>
        ) : platforms.length === 0 ? (
          <PanelSectionRow>
            <Field label="No synced platforms" />
          </PanelSectionRow>
        ) : (
          platforms.map((p) => (
            <PanelSectionRow key={p.slug || p.name}>
              <ButtonItem
                layout="below"
                onClick={() => {
                  showModal(
                    <ConfirmModal
                      strTitle={`Remove ${p.name}`}
                      strDescription={`Remove ${p.count} ${p.name} game${p.count !== 1 ? "s" : ""} from Steam? Downloaded ROMs will not be deleted.`}
                      strOKButtonText="Remove"
                      onOK={async () => {
                        setStatus(`Removing ${p.name}...`);
                        const result = await removePlatformShortcuts(p.slug);
                        if (result.app_ids) {
                          for (const appId of result.app_ids) {
                            removeShortcut(appId);
                          }
                        }
                        if (result.rom_ids?.length) {
                          await reportRemovalResults(result.rom_ids);
                        }
                        clearPlatformCollection(result.platform_name || p.name);
                        // TODO: "Also delete installed ROM files?" option (Phase 3 — download manager needed)
                        setStatus(`Removed ${p.count} ${p.name} game${p.count !== 1 ? "s" : ""}`);
                        refreshPlatforms();
                      }}
                    />
                  );
                }}
              >
                {p.name} ({p.count})
              </ButtonItem>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>

      <PanelSection title="Danger Zone">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => {
              showModal(
                <ConfirmModal
                  strTitle="Remove All Shortcuts"
                  strDescription="Remove all RomM games from your Steam Library? Downloaded ROMs will not be deleted."
                  strOKButtonText="Remove All"
                  onOK={async () => {
                    setStatus("Removing all shortcuts...");
                    const result = await removeAllShortcuts();
                    if (result.app_ids) {
                      for (const appId of result.app_ids) {
                        removeShortcut(appId);
                      }
                    }
                    if (result.rom_ids?.length) {
                      await reportRemovalResults(result.rom_ids);
                    }
                    clearAllRomMCollections();
                    setStatus(result.message);
                    refreshPlatforms();
                  }}
                />
              );
            }}
          >
            Remove All RomM Shortcuts
          </ButtonItem>
        </PanelSectionRow>
        {status && (
          <PanelSectionRow>
            <Field label={status} />
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
};
