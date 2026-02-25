# decky-romm-sync — Implementation Plan

Forward-looking roadmap. Completed phases are summarized at the bottom.
Reference material (API tables, architecture, environment) lives in CLAUDE.md and docs/.

---

## Phase 5: Save File Sync (RetroArch .srm saves) — IN PROGRESS

**Goal**: Bidirectional save file synchronization between RetroDECK and RomM for RetroArch-based systems. Covers per-game `.srm` saves only — standalone emulator saves deferred to Phase 7.

**IMPORTANT**: Save games in RomM are tied to the authenticated user account. Users MUST use their own RomM account so saves are correctly attributed.

### Scope

Systems covered: all RetroArch-core systems (NES, SNES, GB, GBC, GBA, Genesis, N64, PSX, Saturn, Dreamcast, etc.). Save path: `<saves_path>/{system}/{rom_name}.srm` where `saves_path` is read from `retrodeck.json` at runtime.

Standalone emulator saves (PCSX2, DuckStation, Dolphin, PPSSPP, melonDS, etc.) deferred to Phase 7.

### What's implemented

- Three-way conflict detection (local file, last-sync snapshot, server save via hybrid timestamp + download-and-hash)
- Four conflict resolution modes: ask_me (default), newest_wins, always_upload, always_download
- Pre-launch and post-exit sync flows (non-blocking)
- Manual "Sync All Saves Now"
- Device registration (UUID in `save_sync_state.json`)
- Session detection via `SteamClient.GameSessions.RegisterForAppLifetimeNotifications`
- Playtime tracking with suspend/resume pause handling
- Playtime storage via RomM user notes (`romm-sync:playtime`)
- Save sync feature flag (off by default, two-step confirmation to enable)
- Native Steam playtime display via `stateTransaction()` on `SteamAppOverview`
- Conflict resolution popup with Keep Local / Keep Server / Skip
- Save sync settings QAM page with master toggle

### Remaining work

#### 1. Custom Play button — remaining items
Core flow implemented: `handlePlay` does pre-launch sync → conflict modal → launch. Default conflict mode is `ask_me`.

**Not yet done**:
- **Pre-launch toast notifications**: success ("Saves downloaded from RomM"), failure ("Failed to sync saves"), conflict queued

#### ~~6. RomM shared account warning~~ — DONE
Warning in ConnectionSettings when username looks like a shared account. Orange non-blocking warning below username field.

### Verification (unchecked items remaining)
- [ ] Save file uploaded to RomM after play session ends
- [ ] Save file downloaded from RomM before game launch
- [ ] "Newest wins" resolves based on timestamp comparison
- [ ] Manual "Sync All Saves Now" processes all installed ROMs
- [ ] Playtime tracked accurately (suspend/resume excluded)
- [ ] Playtime stored in RomM user notes, readable across devices
- [ ] Device registration persists across plugin restarts
- [ ] Pre-launch and post-exit sync show toast notifications
- [ ] Failed uploads retry 3 times before falling to offline queue
- [ ] Shared account warning shown for generic usernames
- [ ] Game detail page "Saves & Playtime" section greyed out when disabled
- [ ] QAM "Save Sync" button hidden or visually disabled when feature is off
- [ ] Plugin startup skips all save sync initialization when disabled
- [ ] Playtime displayed in Steam's native UI or prominently in game detail panel

---

### Phase 5.6: Unifideck-Style Game Detail Page — IN PROGRESS

> **Design document**: See [`docs/game-detail-ui.md`](docs/game-detail-ui.md) for architecture decisions, React tree findings, and layout design.

**Goal**: Custom game detail page for RomM games. PlaySection with info items mirroring Steam's native layout, plus RomMGameInfoPanel for metadata/actions.

#### What's implemented
- **RomMPlaySection**: Custom PlaySection mirroring Steam's native horizontal bar layout — play button + info items (Last Played, Playtime, Achievements placeholder, Save Sync, BIOS)
- **RomMGameInfoPanel**: Metadata panel below PlaySection
- **CustomPlayButton**: Handles play/download/syncing/conflict/launching states + dropdown menu (Uninstall, BIOS, Sync Saves, Refresh Artwork/Metadata)
- Auto-select play button on page entry (DOM-based focus, 400ms delay)
- RomM gear icon menu + Steam gear icon menu (Properties via `OpenAppSettingsDialog`)
- Cross-component state refresh via `romm_data_changed` events
- Scrolling via DialogButton sections with `scrollIntoView({ block: "center" })`
- SGDB artwork restore (hero, logo, wide grid, icon) on first game detail visit
- Conflict blocking state on CustomPlayButton
- Live reactivity: save sync toggle changes update game detail page immediately
- Delete save files (per-game) and BIOS files (per-platform in DangerZone)
- Live update fixes: post-exit sync, DangerZone, Sync All dispatch `romm_data_changed` events

#### Remaining work

- [ ] **Game detail page: instant load from cache + RomM connection status indicator**

**Problem**: PlaySection and GameInfoPanel take seconds to load, especially when RomM is unavailable.

**Proposed solution — cache-first, then refresh**:
1. **Immediate render from cached data**: On mount, populate UI from local state files (`installed_roms`, `metadata_cache.json`, `shortcut_registry`, `save_sync_state.json`, artwork cache). BIOS defaults to last-known state.
2. **Connection status indicator**: Info item in PlaySection showing "Connecting..." (spinner) → "Connected" (green, refresh live data) → "Offline" (dimmed, cached data only).
3. **Background refresh**: Once connected, silently refresh save/BIOS status and conflict detection. Update UI reactively. This subsumes the "proactive sync check on page open" idea — rather than a separate pre-launch sync on mount, the background refresh handles it. Save status and conflicts are surfaced immediately from cache, then updated live when the server responds.

**Open questions**:
- Should the background refresh do a full `_sync_rom_saves(direction="download")` or just a lightweight status check (list server saves, compare timestamps, detect conflicts without downloading)?
- If a conflict is detected during background refresh, should it show the conflict modal immediately or just update the Play button to "Resolve Conflict" state and let the user initiate resolution?
- How aggressive should the refresh be — every page visit, or only if last check was >N minutes ago?

**Files to modify**: `CustomPlayButton.tsx`, `RomMPlaySection.tsx`, `RomMGameInfoPanel.tsx`, `backend.ts`, `main.py`/`lib/`

#### Future improvements

- **BIOS intelligence**: Distinguish required vs optional BIOS per emulator, emulator-specific requirements, region-specific BIOS. See BIOS intelligence notes in completed Phase 5.6 section.
- **In-Home Streaming Integration**: Research hooking into Steam's Remote Play protocol for "Stream from [device]" option.
- **Unifideck coexistence testing**: Verify both plugins work together without double-injection or gamepad nav issues.

---

## Phase 6: Bug Fixes & Stability

**Goal**: Fix known bugs and improve reliability before adding more features.

### Bug 1: Sync Progress Bar Not Updating
Progress bar appears briefly, then freezes or disappears despite sync completing. Current architecture uses module-level store + 250ms polling from MainPage. Investigation needed to verify event flow end-to-end.

**Related**: Safety timeout (60s) in `_do_sync()` can fire prematurely for large libraries. Consider scaling timeout by ROM count or using heartbeat approach.

### Bug 2: Cancel Sync Not Working
Frontend `_cancelRequested` flag exists but may not be checked during long `await` calls (e.g. `getArtworkBase64()`). Backend cancel only helps while still fetching ROMs — `sync_apply` event is emitted once with full payload.

### Bug 3: RomM M3U Lists BIN Files Instead of CUE
Multi-track single-disc games (e.g. Tomb Raider) get bad M3U files listing `.bin` tracks. Fix: validate M3U after extraction — delete if it only contains `.bin` entries (the CUE file is the correct launch target).

### Bug 4: State Consistency / Startup Pruning
`state.json` can drift from reality after crashes. Solution: startup state healing — prune `installed_roms` entries where file is missing, prune `shortcut_registry` for dead shortcuts, add `.tmp` atomicity for single-file downloads.

### Bug 5: SSL Certificate Verification — CRITICAL for Plugin Store
SSL verification disabled everywhere (4+ locations). Fix: proper verification for public APIs (SteamGridDB) via `certifi` or system CA bundle. User toggle for self-signed certs on RomM (LAN). Consolidate SSL context creation into shared helper.

### Bug 6: Secrets Stored in Plain Text
`settings.json` stores credentials in plain text. Investigate: OS keyring, `chmod 600`, other Decky plugin patterns.

### Bug 7: BIOS Status Reporting
No distinction between required and optional BIOS files. Investigate RomM firmware metadata and RetroArch core requirements.

### Bug 8: VDF-Created Shortcut Icons Not Displaying
Icon path set but not rendered. Investigate format requirements and compare with other plugins.

### Bug 9: Play Button First-Click Failure — FIXED
Resolved by dropping the BIsModOrShortcut bypass counter entirely in Phase 5.6. Shortcuts now return `BIsModOrShortcut() = true` (natural state). We own the entire game detail UI.

### Verification
- [ ] Progress bar shows real-time progress during sync
- [ ] Cancel button stops sync mid-progress
- [ ] Single-disc multi-track game launches via CUE, not bad M3U
- [ ] Startup pruning removes orphaned state entries
- [ ] Shortcut icons display correctly in Steam

---

## Phase 7: Multi-Emulator Support (Deferred)

**Goal**: Support EmuDeck, standalone RetroArch, and manual emulator installs beyond RetroDECK. Extends save sync to standalone emulators.

### Emulator platform presets
- **RetroDECK** (current): Paths from `retrodeck.json`
- **EmuDeck**: `~/Emulation/{roms,bios,saves}/`
- **Manual**: All paths user-configurable

### Configurable paths
ROM directory, BIOS directory, save directory, emulator launch command — all stored in `settings.json`.

### Per-system emulator/core selection
New "Emulators" QAM sub-page. Per-game override on detail page. Resolution: per-game → per-system → preset default.

### Standalone emulator save sync

Extends Phase 5 to standalone emulator save formats:

| Platform | Emulator | Save Path (relative to saves_path) | Format |
|----------|----------|-------------------------------------|--------|
| psx | DuckStation | `psx/duckstation/memcards/` | `.mcd` shared memory cards |
| ps2 | PCSX2 | `ps2/pcsx2/memcards/` | `.ps2` shared memory cards |
| gc | Dolphin | `gc/dolphin/{US,EU,JP}/` | Per-region `.gci` files |
| wii | Dolphin | `wii/dolphin/` | Wii save data + `sd.raw` |
| nds | melonDS | `nds/melonds/` | Per-game `.sav` files |
| n3ds | Azahar | `n3ds/azahar/` | NAND/SDMC title ID structure |
| PSP | PPSSPP | `PSP/PPSSPP-SA/SAVEDATA/` | Title ID directories |
| switch | Ryubing | `switch/ryubing/` | User profile-based saves |
| wiiu | Cemu | `wiiu/cemu/` | mlc01 title ID structure |

**Shared challenges**: Title ID mapping (ROM filename → emulator title ID), shared memory cards (system-level sync, not per-game), streaming multipart upload for files >1MB (current `_romm_upload_multipart` reads entire file into memory — fine for <64KB `.srm` files, not for 8MB PS2 memory cards).

---

## Phase 8: Polish & Advanced Features (Deferred)

- **Multi-version/language ROM selector**: Dropdown when multiple versions exist
- **Auto sync interval**: Configurable background re-sync
- **Library management**: Detect removed/updated ROMs, stale state cleanup
- **Offline mode**: Cache lists locally, queue operations
- **Stacked sync progress UI**: Phased checklist instead of single progress bar
- **Error handling**: Retry with backoff, toast notifications, detailed logging
- **Connection settings UX**: Remove save button, save on popup confirm
- **RomM playtime API**: When feature request #1225 ships, plug in delta-based accumulation
- **Emulator save state sync**: RetroArch `.state` files (larger, version-specific, multiple slots)
- **Steam gear menu**: Add to Favorites, Collections, Hide Game, etc.
- **Save backup on enable**: Prompt to create local save backup when toggling save sync on, and as option during conflict resolution
- **Screenshots gallery**: Custom IGDB screenshot gallery in game detail (deferred from Phase 4C)

---

## External Review Findings

Items from a full code review of `main` and `feat/phase-5-save-sync` branches. New items not tracked elsewhere:

### EXT-1: Platform Map Caching
`_load_platform_map()` reads `config.json` from disk on every `_resolve_system()` call. Cache once on init.

### EXT-2: Atomic Writes for Settings
`_save_state()` and `_save_save_sync_state()` use atomic writes correctly. `_save_settings_to_disk()` does not — apply same `.tmp` + `os.replace()` pattern.

### EXT-3: Download Queue Memory Growth
`_download_queue` grows indefinitely. Prune completed/failed entries after N days or max queue size.

### EXT-4: HTTP Client Code Duplication
Four places independently build SSL contexts + Basic Auth headers. Extract shared `_get_ssl_context()` + `_get_auth_header()` helpers in `romm_client.py`. Critical for SSL fix (Bug 5) and future OAuth2 support.

### EXT-5: Blocking I/O in Async Callables
`_sync_rom_saves()` uses `time.sleep()` in `_with_retry()`. Safe because Decky `callable()` runs in thread pool. Document assumption; wrap in `run_in_executor` if threading model changes.

### EXT-6: Shell Interpolation in Launcher
`bin/romm-launcher` interpolates `$ROM_ID` into Python strings. Regex-validated (digits only) so safe, but fragile. Consider environment variables instead.

### EXT-7: No Rate Limiting on RomM API During Sync
Rapid sequential requests during batch sync. Add configurable delay for remote/slow servers.

---

## Future Improvements (nice-to-have)

- **Concurrent download queue**: Multiple queued downloads
- **RomM native device sync**: Migrate to RomM v4.7+ server-side conflict detection when available
- **Download queue priority/reordering**
- **Developer vs Publisher distinction**: RomM's `companies` is flat — research IGDB's `involved_companies` relationship for proper split
- **RetroAchievements integration**: Show/track via RomM's RA data, direct API, or existing Decky plugin
- **Sync completion notification accuracy**: Track new vs updated vs unchanged shortcuts, show accurate breakdown
- **Library home playtime display**: Non-Steam shortcuts show "Never Played" despite tracked playtime. Steam doesn't persist `minutes_playtime_forever` for shortcuts. No known solution — all similar plugins have same limitation. Our game detail page shows accurate playtime.
- **Playtime sync between RomM and Steam**: Bidirectional cross-device playtime merging
- **UI settings page**: Machine-scoped collections toggle, device labels toggle, custom device name
- **Per-game sync selection**: Select/deselect individual games within a platform
- **Translations / i18n**: Adapt to user's Steam language (reference: Unifideck `src/i18n/`)
- **Global launch interceptor**: Safety net via `SteamClient.Apps.RegisterForGameActionStart` for launches from context menus/search/recent games (outside game detail page). Currently save sync and conflict checks only run when launching from the game detail page.
- **Async/blocking audit**: Systematic review of all `callable()` handlers for blocking I/O that runs directly on the async event loop instead of in `run_in_executor`. Decky's `callable()` dispatches on the main asyncio loop — any synchronous HTTP call, file I/O, or `time.sleep()` blocks all other callables until it returns. `save_sync.py` was partially fixed (wrapped `_sync_rom_saves`, `_with_retry`, `_sync_playtime_to_romm` in `run_in_executor`), but the same pattern likely exists in `romm_client.py`, `downloads.py`, `sync.py`, `firmware.py`, `metadata.py`, and `sgdb.py`. Audit every `async def` callable for blocking calls and wrap them.
- **Save sync conflict architecture refactor**: Remove `pending_conflicts` persistence from `save_sync_state.json` in favor of fully live conflict detection. Currently conflicts are detected live (hash + timestamp) but then stored to disk and looked up later during resolution — this creates stale state risks and unnecessary complexity. Proposed changes:
  1. **Drop `pending_conflicts` from state file.** Every entry point (pre-launch, post-exit, manual sync, lightweight check) already does live detection. No need to persist between detections.
  2. **Derive `server_save_id` at resolution time.** Instead of storing it at detection time, `resolve_conflict()` should list saves for the ROM via API and match by filename. Eliminates the main reason for persistence.
  3. **Lightweight check should show "Possible Conflict"** instead of "Conflict" — it only compares timestamps/sizes, not hashes. Full confirmation happens on Play click. Avoids false positives scaring users.
  4. **Gear menu "Sync Saves" should show conflict modal.** Currently `syncRomSaves()` silently queues conflicts without user notification. Should behave like pre-launch sync: detect conflict → show modal → resolve or skip. Same for "Sync Saves" in SaveSyncSettings QAM page.
  5. **Pass conflict data through frontend round-trip.** `preLaunchSync()` already returns full conflict details (sizes, timestamps, server_save_id). Frontend shows modal, user picks resolution, frontend passes details back to `resolve_conflict()`. No backend state lookup needed.
- **Multi-save-file support**: Current logic assumes one `.srm` per ROM (RetroArch pattern). RomM's API supports multiple saves per ROM (different slots, emulators, devices). Locally, standalone emulators like PCSX2/Dolphin use shared memory cards or per-slot saves. Filename matching works for 1:1 but breaks with multiple files. Needs: enumerate all local + server saves per ROM, match by filename, detect conflicts per file, resolve individually or batch. Ties into Phase 7 standalone emulator save sync.

---

## Completed Phases (Summary)

### Phase 1: Plugin Skeleton + Settings ✅
Plugin loads in Decky, QAM shows settings, connects to RomM. Settings persistence, connection test, platform mapping (149 entries). Released as v0.1.0.

### Phase 2: Sync + Steam Shortcuts ✅
All RomM games appear as Non-Steam shortcuts via `SteamClient.Apps.AddShortcut()`. Artwork via URL-encoding fix. Per-platform sync toggles. Per-platform and bulk removal in DangerZone. Collections via `collectionStore` API. State persistence.

### Phase 3: Download Manager + Multi-Disc ✅
On-demand ROM downloads with progress tracking. Multi-disc support (M3U handling). Pre-download storage check. Download request from launcher. Game detail page injection showing install status. Uninstall All in DangerZone.

### Phase 3.5: Pre-Alpha Bug Fixes ✅
7 bugs fixed: gamepad navigation on detail page (Focusable → DialogButton), launcher state path + `-s` flag removal, Steam Input three-option dropdown (Default/Force On/Force Off), BIOS download from RomM firmware API, BIOS slug mapping (`psx` → `["psx", "ps"]`), BIOS list collapse, RetroArch `input_driver` fix (`"x"` → `"sdl2"` for Wayland).

### Phase 4: Artwork, Metadata & Native Steam Integration ✅
**4A — Full Artwork**: SteamGridDB integration for hero banner, logo, wide grid (via `igdb_id` → `sgdb_id` lookup). Logo position saved. Artwork cached to disk. Icon via VDF write (display issues tracked in Bug 8).
**4B — Native Metadata**: Store patching via `afterPatch` (descriptions, developers, genres, release date, controller support). On-demand fetch + 7-day cache in `metadata_cache.json`.
**4C — Screenshots**: Deferred to Phase 8.

### Phase 4.5: Bug Fixes + Codebase Restructuring ✅
**Bug fixes**: Download button on Steam Deck, DangerZone count refresh (modal → inline confirmation), Steam Remote Play phantom shortcuts documented + DangerZone protected.
**Restructuring**: `main.py` split into `lib/` mixin modules (state, romm_client, sgdb, steam_config, firmware, metadata, downloads, sync, save_sync). Tests split from monolithic `test_main.py` into per-module files.
