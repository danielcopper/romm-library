/** Shared RomM connection state — set by RomMPlaySection, read by CustomPlayButton and sessionManager */
let _state: "checking" | "connected" | "offline" = "checking";
export function getRommConnectionState() { return _state; }
export function setRommConnectionState(s: "checking" | "connected" | "offline") { _state = s; }
