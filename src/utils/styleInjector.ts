import { findSP } from "@decky/ui";

const ROMM_PLAY_HIDE_ID = "romm-hide-native-play";
const ROMM_FOCUS_STYLES_ID = "romm-focus-styles";
const ROMM_INFO_ITEMS_ID = "romm-info-items-styles";

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
}

export function showNativePlaySection() {
  const sp = findSP();
  if (!sp?.window?.document) return;
  sp.window.document.getElementById(ROMM_PLAY_HIDE_ID)?.remove();
  sp.window.document.getElementById(ROMM_FOCUS_STYLES_ID)?.remove();
  sp.window.document.getElementById(ROMM_INFO_ITEMS_ID)?.remove();
}
