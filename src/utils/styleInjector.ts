import { findSP } from "@decky/ui";

const ROMM_PLAY_HIDE_ID = "romm-hide-native-play";
const ROMM_FOCUS_STYLES_ID = "romm-focus-styles";

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
}`;
    sp.window.document.head.appendChild(focusStyle);
  }
}

export function showNativePlaySection() {
  const sp = findSP();
  if (!sp?.window?.document) return;
  sp.window.document.getElementById(ROMM_PLAY_HIDE_ID)?.remove();
  sp.window.document.getElementById(ROMM_FOCUS_STYLES_ID)?.remove();
}
