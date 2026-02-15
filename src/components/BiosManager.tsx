import { useState, useEffect, FC } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  Focusable,
} from "@decky/ui";
import { getFirmwareStatus, downloadAllFirmware } from "../api/backend";
import type { FirmwarePlatform } from "../types";

interface BiosManagerProps {
  onBack: () => void;
}

export const BiosManager: FC<BiosManagerProps> = ({ onBack }) => {
  const [platforms, setPlatforms] = useState<FirmwarePlatform[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  const refresh = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getFirmwareStatus();
      if (result.success) {
        setPlatforms(result.platforms);
      } else {
        setError(result.message || "Failed to fetch firmware status");
      }
    } catch (e) {
      setError(`Failed to fetch firmware status: ${e}`);
    }
    setLoading(false);
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleDownloadAll = async (platformSlug: string) => {
    setDownloading(platformSlug);
    setStatus("");
    try {
      const result = await downloadAllFirmware(platformSlug);
      if (result.success) {
        setStatus(result.message || `Downloaded ${result.downloaded} files`);
        await refresh();
      } else {
        setStatus(result.message || "Download failed");
      }
    } catch (e) {
      setStatus(`Download failed: ${e}`);
    }
    setDownloading(null);
  };

  return (
    <>
      <PanelSection title="BIOS Files">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onBack}>
            Back
          </ButtonItem>
        </PanelSectionRow>

        {loading && (
          <PanelSectionRow>
            <Field label="Loading firmware status..." />
          </PanelSectionRow>
        )}

        {error && (
          <PanelSectionRow>
            <Field label="Error" description={error} />
          </PanelSectionRow>
        )}

        {!loading && !error && platforms.length === 0 && (
          <PanelSectionRow>
            <Field label="No firmware files found on server" />
          </PanelSectionRow>
        )}

        {status && (
          <PanelSectionRow>
            <Field label={status} />
          </PanelSectionRow>
        )}
      </PanelSection>

      {platforms.map((platform) => {
        const total = platform.files.length;
        const done = platform.files.filter((f) => f.downloaded).length;
        const allDone = done === total;
        const isDownloading = downloading === platform.platform_slug;

        return (
          <PanelSection key={platform.platform_slug} title={platform.platform_slug}>
            <PanelSectionRow>
              <Field
                label={`${done} / ${total} files`}
                description={allDone ? "All downloaded" : `${total - done} missing`}
              />
            </PanelSectionRow>
            <Focusable>
              {platform.files.map((file) => (
                <PanelSectionRow key={file.id}>
                  <Field
                    label={file.file_name}
                    description={file.downloaded ? "\u2713" : "Missing"}
                  />
                </PanelSectionRow>
              ))}
            </Focusable>
            {!allDone && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() => handleDownloadAll(platform.platform_slug)}
                  disabled={isDownloading}
                >
                  {isDownloading ? "Downloading..." : "Download All"}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </PanelSection>
        );
      })}
    </>
  );
};
