import { useState, useEffect, FC } from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  Field,
  Focusable,
} from "@decky/ui";
import { getFirmwareStatus, downloadAllFirmware, downloadRequiredFirmware } from "../api/backend";
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

  const handleDownloadRequired = async (platformSlug: string) => {
    setDownloading(platformSlug);
    setStatus("");
    try {
      const result = await downloadRequiredFirmware(platformSlug);
      if (result.success) {
        setStatus(result.message || `Downloaded ${result.downloaded} required files`);
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
    const isExpanded = expanded[platform.platform_slug] ?? false;

    const requiredFiles = platform.files.filter((f) => f.required);
    const optionalFiles = platform.files.filter((f) => !f.required);
    const requiredCount = requiredFiles.length;
    const requiredDone = requiredFiles.filter((f) => f.downloaded).length;
    const allRequiredDone = requiredDone === requiredCount;
    const optionalDone = optionalFiles.filter((f) => f.downloaded).length;
    const optionalMissing = optionalFiles.length - optionalDone;

    const needsAttention = platform.has_games && !allRequiredDone;

    let summaryLabel: string;
    let summaryDescription: string;
    if (requiredCount > 0) {
      if (allRequiredDone) {
        summaryLabel = `${requiredDone} / ${requiredCount} required`;
        summaryDescription = optionalMissing > 0
          ? `All required ready (${optionalMissing} optional missing)`
          : "All required ready";
      } else {
        summaryLabel = `${requiredDone} / ${requiredCount} required`;
        summaryDescription = `${requiredCount - requiredDone} required missing — games may not launch`;
      }
    } else {
      summaryLabel = `${done} / ${total} files`;
      summaryDescription = allDone ? "All downloaded" : `${total - done} missing`;
    }

    const hashIndicator = (hv: boolean | null) =>
      hv === true ? " \u2713" : hv === false ? " \u26A0" : " \u2014";

    const hasRequiredMissing = requiredCount > 0 && !allRequiredDone;
    const hasOptionalMissing = optionalMissing > 0;

    return (
      <PanelSection
        key={platform.platform_slug}
        title={`${platform.platform_slug}${needsAttention ? " — BIOS needed" : ""}`}
      >
        <PanelSectionRow>
          <Field
            label={summaryLabel}
            description={summaryDescription}
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
                  label={`${file.description || file.file_name} (${file.required ? "required" : "optional"})`}
                  description={
                    file.downloaded
                      ? `${file.file_name}${hashIndicator(file.hash_valid)}`
                      : `${file.file_name} — Missing`
                  }
                />
              </PanelSectionRow>
            ))}
          </Focusable>
        )}
        {hasRequiredMissing && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => handleDownloadRequired(platform.platform_slug)}
              disabled={isDownloading}
            >
              {isDownloading ? "Downloading..." : "Download Required"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {!allDone && (hasOptionalMissing || hasRequiredMissing) && (
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
