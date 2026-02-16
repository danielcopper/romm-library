import { useState, useEffect, FC } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  Focusable,
} from "@decky/ui";
import { getFirmwareStatus, downloadAllFirmware } from "../api/backend";
import type { FirmwarePlatformExt } from "../types";

interface BiosManagerProps {
  onBack: () => void;
}

export const BiosManager: FC<BiosManagerProps> = ({ onBack }) => {
  const [platforms, setPlatforms] = useState<FirmwarePlatformExt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

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

  // Separate platforms with games (show first, more prominent) from others
  const withGames = platforms.filter((p) => p.has_games);
  const withoutGames = platforms.filter((p) => !p.has_games);

  const renderPlatform = (platform: FirmwarePlatformExt) => {
    const total = platform.files.length;
    const done = platform.files.filter((f) => f.downloaded).length;
    const allDone = done === total;
    const isDownloading = downloading === platform.platform_slug;
    const needsAttention = platform.has_games && !allDone;
    const isExpanded = expanded[platform.platform_slug] ?? false;

    return (
      <PanelSection
        key={platform.platform_slug}
        title={`${platform.platform_slug}${needsAttention ? " — BIOS needed" : ""}`}
      >
        <PanelSectionRow>
          <Field
            label={`${done} / ${total} files`}
            description={
              allDone
                ? "All downloaded"
                : needsAttention
                  ? `${total - done} missing — games may not launch`
                  : `${total - done} missing`
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => setExpanded((prev) => ({
              ...prev,
              [platform.platform_slug]: !prev[platform.platform_slug],
            }))}
          >
            {isExpanded ? "Hide Files" : `Show Files (${total})`}
          </ButtonItem>
        </PanelSectionRow>
        {isExpanded && (
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
        )}
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

      {withGames.map(renderPlatform)}
      {withoutGames.map(renderPlatform)}
    </>
  );
};
