import { findSP } from "@decky/ui";

const ROMM_PLAY_HIDE_ID = "romm-hide-native-play";
const ROMM_FOCUS_STYLES_ID = "romm-focus-styles";
const ROMM_INFO_ITEMS_ID = "romm-info-items-styles";
const ROMM_GAME_INFO_PANEL_ID = "romm-game-info-panel-styles";
const ROMM_GEAR_BUTTONS_ID = "romm-gear-btn-styles";

export function hideNativePlaySection(playSectionClass: string) {
  const sp = findSP();
  if (!sp?.window?.document) return;

  // Hide native PlaySection — display:none + visibility:hidden + pointer-events:none
  // All three are needed: display:none hides visually, visibility:hidden is belt-and-suspenders,
  // pointer-events:none is CRITICAL to remove from gamepad focus traversal
  if (!sp.window.document.getElementById(ROMM_PLAY_HIDE_ID)) {
    const style = sp.window.document.createElement("style");
    style.id = ROMM_PLAY_HIDE_ID;
    style.textContent = `.${playSectionClass}:not([data-romm]) {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}`;
    sp.window.document.head.appendChild(style);
  }

  // Inject .gpfocus styles for our custom buttons — Steam applies this class
  // automatically during gamepad navigation to indicate focus
  if (!sp.window.document.getElementById(ROMM_FOCUS_STYLES_ID)) {
    const focusStyle = sp.window.document.createElement("style");
    focusStyle.id = ROMM_FOCUS_STYLES_ID;
    focusStyle.textContent = `
.romm-btn-download:hover, .romm-btn-download.gpfocus {
  background: linear-gradient(to right, #0d8bf0, #0068c0) !important;
  filter: brightness(1.2);
}
.romm-btn-play:hover, .romm-btn-play.gpfocus {
  background: linear-gradient(to right, #80e62a, #01b866) !important;
  filter: brightness(1.2);
}
.romm-btn-conflict:hover, .romm-btn-conflict.gpfocus {
  background: linear-gradient(to right, #c49a28, #a6851b) !important;
  filter: brightness(1.2);
}
.romm-btn-dropdown:hover, .romm-btn-dropdown.gpfocus {
  filter: brightness(1.3);
}
[data-romm] .gpfocus {
  outline: 2px solid #1a9fff;
  outline-offset: 2px;
}
@keyframes romm-spin {
  to { transform: rotate(360deg); }
}
.romm-throbber {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: romm-spin 0.8s linear infinite;
  flex-shrink: 0;
}`;
    sp.window.document.head.appendChild(focusStyle);
  }

  // Info items styles for RomMPlaySection (Last Played, Playtime, Save Sync, BIOS)
  if (!sp.window.document.getElementById(ROMM_INFO_ITEMS_ID)) {
    const infoStyle = sp.window.document.createElement("style");
    infoStyle.id = ROMM_INFO_ITEMS_ID;
    infoStyle.textContent = `
.romm-info-items {
  margin-left: 16px;
}
.romm-info-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.romm-info-header {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #8f98a0;
  line-height: 1.2;
  white-space: nowrap;
}
.romm-info-value {
  font-size: 13px;
  font-weight: 500;
  color: #dcdedf;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.romm-info-muted .romm-info-value {
  color: #5e6770;
  font-style: italic;
}
.romm-status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}`;
    sp.window.document.head.appendChild(infoStyle);
  }

  // Game info panel styles for RomMGameInfoPanel (Description, Metadata, Genres, ROM File)
  if (!sp.window.document.getElementById(ROMM_GAME_INFO_PANEL_ID)) {
    const panelStyle = sp.window.document.createElement("style");
    panelStyle.id = ROMM_GAME_INFO_PANEL_ID;
    panelStyle.textContent = `
.romm-panel-container {
  display: flex;
  flex-direction: column;
  padding: 16px 2.8vw;
  gap: 16px;
  background: rgba(14, 20, 27, 0.33);
}
.romm-panel-section {
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.romm-panel-section:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.romm-panel-section-title {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: #8f98a0;
  margin-bottom: 8px;
  line-height: 1.2;
}
.romm-panel-summary {
  color: #acb2b8;
  font-size: 13px;
  line-height: 1.5;
  margin-bottom: 8px;
}
.romm-panel-info-row {
  display: flex;
  align-items: baseline;
  gap: 16px;
  padding: 2px 0;
}
.romm-panel-label {
  color: #8f98a0;
  font-size: 12px;
  flex-shrink: 0;
  min-width: 120px;
}
.romm-panel-value {
  color: #dcdedf;
  font-size: 13px;
}
.romm-panel-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.romm-panel-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 3px;
  background: rgba(255,255,255,0.06);
  color: #8f98a0;
  border: 1px solid rgba(255,255,255,0.1);
}
.romm-panel-status-row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.romm-panel-status-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 3px;
  font-weight: 600;
}
.romm-panel-status-installed {
  background: rgba(91,163,43,0.2);
  color: #5ba32b;
}
.romm-panel-status-not-installed {
  background: rgba(143,152,160,0.15);
  color: #8f98a0;
}
.romm-panel-platform-badge {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 3px;
  font-weight: 600;
  background: rgba(26,159,255,0.15);
  color: #1a9fff;
}
.romm-panel-actions-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.romm-panel-action-btn {
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 3px;
  background: rgba(255,255,255,0.06);
  color: #dcdedf;
  border: 1px solid rgba(255,255,255,0.1);
  cursor: pointer;
}
.romm-panel-action-btn:hover, .romm-panel-action-btn.gpfocus {
  background: rgba(255,255,255,0.12);
  filter: brightness(1.1);
}
.romm-panel-action-destructive {
  color: #d94126;
  border-color: rgba(217,65,38,0.3);
}
.romm-panel-action-destructive:hover, .romm-panel-action-destructive.gpfocus {
  background: rgba(217,65,38,0.15);
}
.romm-panel-muted {
  color: #5e6770;
  font-size: 13px;
  font-style: italic;
}
.romm-panel-loading {
  color: #8f98a0;
  font-size: 13px;
  padding: 8px 0;
}
.romm-panel-status-action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.romm-panel-status-inline {
  display: flex;
  align-items: center;
  gap: 8px;
}
.romm-panel-file-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
}
.romm-panel-file-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.romm-panel-file-name {
  font-size: 12px;
  color: #dcdedf;
  font-weight: 500;
}
.romm-panel-file-path {
  font-size: 11px;
  color: #5e6770;
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.romm-panel-file-detail {
  font-size: 11px;
  color: #8f98a0;
  white-space: nowrap;
}
.romm-panel-file-conflict {
  font-size: 11px;
  color: #d94126;
  font-weight: 600;
}`;
    sp.window.document.head.appendChild(panelStyle);
  }

  // Gear icon button styles for RomMPlaySection (RomM actions + Steam properties)
  if (!sp.window.document.getElementById(ROMM_GEAR_BUTTONS_ID)) {
    const gearStyle = sp.window.document.createElement("style");
    gearStyle.id = ROMM_GEAR_BUTTONS_ID;
    gearStyle.textContent = `
.romm-gear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.06);
  cursor: pointer;
  transition: background 0.15s ease, filter 0.15s ease;
  padding: 0;
  flex-shrink: 0;
}
.romm-gear-btn:hover, .romm-gear-btn.gpfocus {
  background: rgba(255,255,255,0.14);
  filter: brightness(1.2);
}
.romm-gear-btn:active {
  filter: brightness(0.9);
}`;
    sp.window.document.head.appendChild(gearStyle);
  }
}

export function showNativePlaySection() {
  const sp = findSP();
  if (!sp?.window?.document) return;
  sp.window.document.getElementById(ROMM_PLAY_HIDE_ID)?.remove();
  sp.window.document.getElementById(ROMM_FOCUS_STYLES_ID)?.remove();
  sp.window.document.getElementById(ROMM_INFO_ITEMS_ID)?.remove();
  sp.window.document.getElementById(ROMM_GAME_INFO_PANEL_ID)?.remove();
  sp.window.document.getElementById(ROMM_GEAR_BUTTONS_ID)?.remove();
}
