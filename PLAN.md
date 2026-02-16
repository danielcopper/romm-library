# romm-library — Decky Loader Plugin Implementation Plan

## Context

Self-hosted RomM server manages a ROM collection on Unraid. Goal: browse and play the entire RomM library directly from Steam Gaming Mode on a Bazzite HTPC, with on-demand downloads and correct RetroDECK emulator launches. No existing tool does this — DeckRomMSync is alpha/full-sync-only, Playnite RomM plugin is Windows-only.

**Core concept**: ALL RomM games appear as Non-Steam shortcuts in the Steam Library. The Decky QAM panel is only for settings, sync, and download management. This follows the Unifideck pattern (GPL-3.0, compatible with our GPL-3.0 license).

## Key Decisions

- **Play on undownloaded game**: Launcher triggers background download via plugin backend, exits cleanly. User gets toast notification. Play again when done.
- **Emulator**: RetroDECK (`flatpak run net.retrodeck.retrodeck [-e emulator] [-s system] <rom>`). Supports per-system and per-game emulator override.
- **Shortcut creation**: Use `SteamClient.Apps.AddShortcut()` from the frontend (NOT direct VDF writes). Steam does not watch shortcuts.vdf — direct VDF edits require a restart. The SteamClient API creates shortcuts instantly in Steam's live state.
- **Frontend**: `@decky/ui` + `@decky/api` (NOT deprecated `decky-frontend-lib`)
- **Backend comms**: `callable()` from `@decky/api` (NOT `ServerAPI.callPluginMethod()`)
- **RomM Auth**: HTTP Basic Auth (OAuth2 Bearer as future option)
- **Download endpoint**: `GET /api/roms/{id}/content/{file_name}` — returns single file or ZIP for multi-file ROMs (includes M3U if applicable). Always download all files (no partial downloads).
- **RomM API quirks**: ROM filtering uses `platform_ids` (plural). Cover image URLs contain unencoded spaces (must URL-encode). Paginated responses use `{"items": [...], "total": N}` envelope.

## Environment & Git Setup

We are inside a **Distrobox container `dev`** (Fedora 43) on a Bazzite HTPC. The home directory is shared between host and container.

**SSH for git push**: The SSH agent runs on the host. Claude Code must set `SSH_AUTH_SOCK` for every git push/pull:
```bash
SSH_AUTH_SOCK=/tmp/ssh-XXXXXX7kJjym/agent.61196 git push
```
The socket path may change between sessions. If push fails with "Permission denied (publickey)", **ask Daniel to re-run `ssh-add`** in his terminal and provide the new socket path.

**When to ask Daniel (human) for help:**
- SSH agent expired or socket path changed → ask to `ssh-add` again
- `sudo dnf install` needed for new system packages → ask to run in terminal
- Testing in Gaming Mode → ask to switch to Gaming Mode and check
- RomM server credentials or URL → ask for connection details
- Any destructive action on Steam shortcuts or ROM files → confirm first

## Architecture

```
RomM Server ←HTTP→ Python Backend (main.py)
                        ↓ callable()
              Frontend (TypeScript) ←→ SteamClient.Apps API
                        ↓
                   Steam Library (shortcuts appear instantly)
                        ↓
                   bin/romm-launcher (bash)
                        ↓
                   RetroDECK (flatpak)
```

**Shortcut creation flow**: Python backend fetches ROM data from RomM → passes to frontend via callable() → frontend calls `SteamClient.Apps.AddShortcut()` → shortcut appears in Steam instantly. Python backend still handles: RomM API calls, ROM downloads, artwork downloads, state persistence, file I/O.

Every shortcut: `exe` → `bin/romm-launcher`, `LaunchOptions` → `romm:{rom_id}`. Launcher checks install status, either launches RetroDECK or requests download.

## RomM API Reference (key endpoints)

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/api/heartbeat` | GET | Health check (no auth needed) |
| `/api/platforms` | GET | All platforms (plain list) |
| `/api/roms?platform_ids={id}&limit=50&offset=N` | GET | ROMs by platform (paginated envelope) |
| `/api/roms/{id}` | GET | Full ROM detail (includes `files`, `user_saves`, `user_states`, metadata) |
| `/api/roms/{id}/content/{file_name}` | GET | Download ROM (single file or ZIP for multi-file, includes M3U) |
| `/api/romsfiles/{file_id}/content/{file_name}` | GET | Download individual file from multi-file ROM |
| `/api/saves` | GET/POST | List/upload saves. Filter by `rom_id`, `platform_id`. Upload via multipart form (`saveFile`) |
| `/api/saves/{id}` | GET/PUT | Get/update specific save |
| `/api/saves/{id}/content` | GET | Download save file binary |
| `/api/saves/delete` | POST | Batch delete saves `{"saves": [id, ...]}` |
| `/api/states` | GET/POST | Same as saves but for emulator save states |
| `/api/states/{id}/content` | GET | Download state file binary |

## SteamClient.Apps API Reference (for shortcut management)

Available from the Decky frontend JS context. Shortcuts appear instantly without restart.

| Method | Signature | Notes |
|--------|-----------|-------|
| `AddShortcut` | `(appName, exe, startDir, launchOptions) → Promise<number>` | Creates shortcut, returns app ID |
| `RemoveShortcut` | `(appId) → void` | Removes shortcut instantly |
| `SetShortcutName` | `(appId, name) → void` | Sets display name |
| `SetShortcutExe` | `(appId, path) → void` | Sets executable |
| `SetShortcutStartDir` | `(appId, dir) → void` | Sets working directory |
| `SetShortcutLaunchOptions` | `(appId, options) → void` | Sets launch options |
| `SetCustomArtworkForApp` | `(appId, artworkPath, artworkType) → void` | Sets grid/hero/logo artwork |

## RetroDECK Integration Reference

**CLI**: `flatpak run net.retrodeck.retrodeck [-e emulator] [-s system] [-m] <game_path>`

**Emulator resolution order** (when no `-e` flag):
1. Per-game `<altemulator>` in `gamelist.xml`
2. Per-system `<alternativeEmulator>` in `gamelist.xml`
3. First `<command>` in `es_systems.xml` (the default)

**Systems with multiple emulators** (examples):
- PSX: SwanStation (default), Beetle PSX, Beetle PSX HW, PCSX ReARMed, DuckStation
- PS2: PCSX2 Standalone (default), LRPS2, PCSX2 RetroArch core
- Dreamcast: Flycast RetroArch (default)
- All disc-based systems support `.m3u` extension

**Save file locations** (RetroDECK):
- RetroArch saves: `~/retrodeck/saves/{system}/`
- RetroArch states: `~/retrodeck/states/{system}/`
- Standalone emulator saves vary by emulator

---

## Phase 1: Plugin Skeleton + Settings ✅ DONE

**Goal**: Plugin loads in Decky, QAM shows settings, can connect to RomM.

- Plugin manifest, build config, TypeScript frontend, Python backend
- Settings persistence, connection test, platform mapping (149 entries)
- Merged to main as v0.1.0

## Phase 2: Sync + Steam Shortcuts ✅ DONE

**Goal**: All RomM games appear in Steam Library with artwork and collections.

### Completed:
- SteamClient.Apps API migration (instant shortcuts, no Steam restart)
- sync_apply event flow: backend emits shortcut data → frontend creates via SteamClient → reports app_ids back
- Artwork download with URL-encoding fix for RomM's unencoded spaces
- Artwork staging pattern (romm_{rom_id}_cover.png → {app_id}p.png) survives remove+re-add
- Per-item artwork via `get_artwork_base64(rom_id)` callable (avoids bulk base64 WebSocket crash)
- Post-AddShortcut delay increased to 500ms for reliable artwork application
- Paginated ROM fetching with `platform_ids` parameter (fixed from `platform_id`)
- Per-platform sync toggle with enable/disable all
- Drill-down QAM navigation (Main → Connection / Platforms / Danger Zone)
- Per-platform removal in Danger Zone
- Library stats computed live from registry
- Sync progress spinner: stays visible during frontend processing, auto-clears after 8s
- State persistence (shortcut_registry, sync_stats)
- Collections via correct `collectionStore` API: `NewUnsavedCollection()` + `AsDragDropCollection().AddApps()` + `Save()`
- Collections use `appStore.GetAppOverviewByAppID()` for proper app overview objects
- 45 unit tests

### Remaining — Danger Zone: Remove All Non-Steam Games:

**Problem**: Leftover non-steam shortcuts from previous imports (not managed by our plugin) clutter the library. Current Danger Zone only removes RomM-managed shortcuts.

**Feature: "Remove All Non-Steam Games" button** in Danger Zone:
- Enumerates ALL non-steam shortcuts via `collectionStore.deckDesktopApps.apps`
- Confirmation dialog (must confirm twice for safety)
- **Whitelist/Exclude list**: Button that opens a dropdown/checklist of all current non-steam games. User checks items that should NOT be removed (e.g. RetroDECK, other manually added shortcuts). Whitelist persisted in plugin settings.
- Removal calls `SteamClient.Apps.RemoveShortcut()` for each non-whitelisted shortcut

### QAM UI structure (current):
- **Main Page**: Connection status, last sync stats, Sync button + progress, nav buttons
- **Connection Settings**: URL, username, password, save, test
- **Platforms**: Enable/disable toggles per platform with ROM counts
- **Danger Zone**: Per-platform removal + Remove All RomM + Remove All Non-Steam (with whitelist)

## Phase 3: Download Manager + Multi-Disc

**Goal**: Download ROMs on-demand with full multi-disc support. Storage space validation.

### Pre-download storage check:
- Check available disk space on target filesystem before starting download
- Block download with clear error if insufficient space (ROM size + buffer)
- Show file size in download confirmation

### Single-file ROM downloads:
- `start_download(rom_id)` → async download task
- Stream from `/api/roms/{id}/content/{file_name}` to `~/retrodeck/roms/{system}/{file_name}`
- Progress tracking, cancellation, partial file cleanup
- Register in `installed_roms` state on completion
- `emit("download_complete")` for toast notification

### Multi-file / multi-disc ROM handling:

**Detection**: Check `has_multiple_files` flag from ROM API. Inspect `files` array to distinguish:
- **Multi-disc** (PS1, PS2, Saturn): Files named `(Disc 1)`, `(Disc 2)`, etc. + M3U file
- **Multi-track single disc** (audio CDs): Files named `(Track 01)`, etc. + single CUE. Not multi-disc — launch via CUE.
- **Game + DLC/updates** (Switch): Base game + update NSP files. Always download ALL files.
- **Extracted directories** (Wii U, PS3): Hundreds of files. Download ZIP, extract to ROM dir.

**Download flow for multi-file ROMs**:
1. `GET /api/roms/{id}/content/{name}` returns a ZIP containing all files + M3U (if applicable)
2. Extract ZIP to `~/retrodeck/roms/{system}/{rom_name}/`
3. Detect launch file:
   - If `.m3u` exists → store as launch path (for multi-disc)
   - Else if `.cue` exists → store as launch path (for single disc with tracks)
   - Else → first/largest file
4. Store launch file path in `installed_roms` state

**M3U auto-generation setting**: If ROM has multiple disc files but no M3U included from RomM, optionally auto-generate one (toggle in settings, default: on).

### Download request from launcher:
- `_poll_download_requests()` — async loop checking `download_requests.json` every 2s
- Launcher writes request, plugin picks it up and starts download
- Toast notification when download completes

### Frontend — QAM additions:

**Download Queue sub-page** (new nav button on Main Page):
- Active downloads with progress bars, cancel buttons
- Completed/failed downloads list

**Downloads Settings sub-page** (new nav button on Main Page):
- Download location override (default: `~/retrodeck/roms/{system}/`)
- M3U auto-generation toggle

**Game detail page injection** (route patch):
- `routerHook.addPatch("/library/app/:appid", ...)` using findInReactTree
- Show: "Not installed" + Download / Progress + Cancel / "Installed" + Uninstall
- `getRomBySteamAppId(appId)` to identify RomM games

### M3U testing checklist:
- [ ] Download a multi-disc PS1 ROM (e.g. FF7) from RomM via the API
- [ ] Verify ZIP contains M3U file
- [ ] Verify M3U content lists all disc .cue files correctly
- [ ] Extract and launch via RetroDECK with the M3U
- [ ] Verify disc swapping works in-game
- [ ] Test a multi-track single-disc ROM (e.g. Tomb Raider) — should NOT use M3U
- [ ] Test auto-generation of M3U when RomM doesn't include one

### Danger Zone — Uninstall All Installed ROMs:

**Feature: "Uninstall All Installed ROMs" button** in Danger Zone:
- Removes all downloaded ROM files from `~/retrodeck/roms/{system}/` for installed ROMs tracked in `installed_roms` state
- Confirmation dialog warns: "This will delete all downloaded ROM files. If save sync is available, sync saves to RomM first."
- If Phase 5 (save sync) is implemented, prompt to sync saves before uninstalling
- If Phase 5 is not yet implemented, show warning: "Save files may be lost — back up manually if needed"
- Clears `installed_roms` state after deletion
- Does NOT remove shortcuts — only the ROM files on disk

### Verification:
- [ ] Storage space check prevents download when disk full
- [ ] Single-file ROM download works end-to-end
- [ ] Multi-disc ROM (e.g. FF7) downloads as ZIP, extracts, has working M3U
- [ ] Launcher detects M3U and passes it to RetroDECK
- [ ] Download progress visible in QAM and game detail page
- [ ] Cancel cleans up partial files
- [ ] Game detail page shows correct install status
- [ ] Uninstall all removes ROM files and clears installed state

## Phase 3.5: Pre-Alpha Bug Fixes

**Goal**: Fix blockers preventing a usable alpha release.

### Bug 1: Controller/gamepad can't navigate game detail page — FIXED
- Download/Uninstall buttons on game detail page were plain HTML, not focusable by Steam's gamepad navigation
- **Fix**: Replaced with `Focusable` + `DialogButton` from `@decky/ui`

### Bug 2: Game launch fails silently — FIXED
Two root causes:
- **Wrong state path**: Launcher looked in `homebrew/settings/` but `state.json` lives in `homebrew/data/`. Fixed search candidates.
- **Invalid `-s` flag**: RetroDECK doesn't have a `-s system` flag — auto-detects from `roms/{system}/` directory path. Removed the flag.

### Bug 3: Steam Input conflicts with RetroArch controller — FIXED
**Symptom**: Gamepad works in-game (GBA tested) but RetroArch menu/hotkeys don't function correctly.

**Research findings (deep dive)**:
- `UseSteamControllerConfig` has three values: `"0"` (Force Off), `"1"` (Default), `"2"` (Force On)
- Our initial fix used `"0"` (Force Off) which **caused** the problem — disabling Steam Input entirely breaks controller passthrough on SteamOS/Bazzite
- EmuDeck uses `"1"` (Default) with custom controller templates, NOT Force Off
- RetroDECK **requires** Steam Input to be enabled — its hotkeys (L3+R3 for menu, save states, etc.) depend on it
- Force Off passes raw HID device; RetroArch's menu/hotkey layer doesn't see it properly
- Force On (`"2"`) normalizes the controller as standard XInput gamepad, which is what RetroArch autoconfig expects

**Fix**: Replaced boolean "Disable Steam Input" toggle with three-option dropdown:
- **Default** (`"1"` / remove key) — recommended, uses global Steam settings
- **Force On** (`"2"`) — explicitly enables Steam Input wrapping
- **Force Off** (`"0"`) — raw passthrough, only for advanced users
- "Apply to All Shortcuts" button for immediate application
- Old `disable_steam_input` boolean auto-migrates to `steam_input_mode`

### Bug 4: BIOS files required for disc-based systems — IMPLEMENTED
**Symptom**: PSX Tomb Raider fails to launch — SwanStation core requires BIOS files (e.g. `scph5501.bin`) which are missing from `~/retrodeck/bios/`.

**Research findings**:
- RomM has a full `/api/firmware` endpoint (list, download, filter by platform_id)
- BIOS files downloaded to `~/retrodeck/bios/` with platform-specific subfolders (dc → `dc/`, ps2 → `pcsx2/bios/`, everything else flat)
- MD5 verification against RomM's stored hashes
- No renaming needed — trust filenames as stored in RomM
- BIOS file management (correct naming, checksums) is RomM's or igir's responsibility

**Implementation**:
- Backend: `get_firmware_status()`, `download_firmware(id)`, `download_all_firmware(platform_slug)` callables
- Frontend: BiosManager QAM page showing per-platform firmware status with "Download All" buttons
- Path mapping via `BIOS_DEST_MAP` dict (currently hardcoded to RetroDECK paths — will become configurable in Phase 4)

### Bug 5: BIOS not shown on game detail page — FIXED
- `checkPlatformBios("psx")` failed because RomM stores firmware under `bios/ps` (slug `ps`) but platform slug is `psx`
- **Fix**: Added `_platform_to_firmware_slugs()` mapping so `psx` matches both `["psx", "ps"]`
- Game detail page now always shows BIOS status (green when ready, orange when missing)
- Clickable BIOS status opens modal overlay listing individual BIOS files per platform

### Bug 6: BIOS file lists not collapsible — FIXED
- BiosManager showed all files expanded by default, making long lists hard to navigate
- **Fix**: Added per-platform expand/collapse toggle, collapsed by default

### Bug 7: RetroArch menu not navigable with controller — FIXED
- D-pad/buttons didn't work in RetroArch Quick Menu (L3+R3), only mouse worked
- All three `UseSteamControllerConfig` values (0/1/2) tested — none fixed it
- **Root cause**: `input_driver = "x"` in RetroArch config uses X11 input on a Wayland system; menu navigation relies on `input_driver` while gameplay uses `input_joypad_driver`
- **Fix**: Changed `input_driver` to `"sdl2"` in RetroArch config
- Added diagnostic check in plugin settings: detects `input_driver` value from RetroArch config (checks RetroDECK, RetroArch Flatpak, and native paths) and shows status/warning in Controller section

### Verification:
- [x] Game detail page buttons navigable with controller
- [x] GBA game launches successfully via RetroDECK
- [x] Steam Input dropdown shows three options (Default, Force On, Force Off)
- [x] "Apply to All Shortcuts" writes correct values to VDF
- [x] Controller works in RetroArch menu with input_driver = "sdl2"
- [x] PSX game launches after BIOS download
- [x] BIOS download from RomM works
- [x] BIOS status shown on game detail page with file list overlay
- [x] BIOS file lists collapsed by default in BiosManager
- [x] RetroArch input_driver diagnostic shown in settings

---

## Phase 4: Multi-Emulator Support + Launch Enhancements

**Goal**: Support RetroDECK, EmuDeck, standalone RetroArch, and manual emulator installs. End-to-end play with correct emulator.

### Emulator platform presets (new settings UI):

**Preset selector** (dropdown in Connection Settings or new "Setup" page):
- **RetroDECK** (current default): `~/retrodeck/roms/`, `~/retrodeck/bios/`, `~/retrodeck/saves/`, launcher: `flatpak run net.retrodeck.retrodeck`
- **EmuDeck**: `~/Emulation/roms/`, `~/Emulation/bios/`, `~/Emulation/saves/`, launcher: per-system emulator paths
- **Manual**: All paths user-configurable

When preset changes, auto-populate all paths. User can still override individually.

### Configurable paths (settings):
- **ROM directory**: Base path for ROM files (default per preset)
- **BIOS directory**: Base path for BIOS/firmware (default per preset)
- **Save directory**: Base path for save files (default per preset, needed for Phase 5)
- **Emulator launch command**: Per-system or global (default per preset)
- All paths stored in `settings.json`
- Update `BIOS_DEST_MAP`, `start_download()`, and launcher to read from settings instead of hardcoded paths

### Enhanced launcher (`bin/romm-launcher`):
- Read emulator platform from settings to determine launch command
- RetroDECK: `flatpak run net.retrodeck.retrodeck <rom_path>` (current behavior)
- EmuDeck: per-system emulator command (needs mapping table)
- Manual: user-configured command per system
- Verify emulator installed before launch attempt
- Error handling with zenity dialogs or toast notifications

### Emulator/core selection:

**Per-system defaults** (new QAM sub-page: "Emulators"):
- List each system with its available emulators
- For RetroDECK: read from config or hardcode common ones, use `-e emulator` flag
- For EmuDeck/manual: select which standalone emulator to use per system
- User selects preferred emulator per system (or "Use default")
- Stored in plugin settings

**Per-game override** (optional):
- On game detail page, option to override emulator for specific game
- Stored in state.json per rom_id

**Resolution order** when launching:
1. Check per-game override in state
2. Check per-system preference in settings
3. Neither set → use preset default

### Verification:
- [ ] Games launch correctly with RetroDECK preset
- [ ] Games launch correctly with EmuDeck preset
- [ ] Manual preset with custom paths works
- [ ] Per-system emulator override works
- [ ] Multi-disc games launch via M3U file
- [ ] Undownloaded game → triggers download → toast → second launch works
- [ ] Emulator not installed → clear error message
- [ ] Switching presets updates all paths correctly

## Phase 5: Save File Sync

**Goal**: Bidirectional save file synchronization between emulators and RomM.

**IMPORTANT: RomM account requirement**: Save games in RomM are tied to the authenticated user account. Users MUST use their own RomM account (not a shared/generic one) so saves are correctly attributed. Document this in README and show a warning in settings if the account appears to be shared (e.g. username is "admin" or "romm").

### Complexity notes:
This is the most complex phase. Save sync requires careful handling of conflicts, timestamps, and emulator-specific save formats. Save file paths depend on the emulator platform preset (Phase 4) — RetroDECK, EmuDeck, and manual installs store saves in different locations.

### Play session detection:
Need to reliably detect when a game session starts and ends. Two main options:
- **Poll RetroDECK process**: Check if `net.retrodeck.retrodeck` flatpak process is running, detect when it exits
- **Steam play tracking**: Use `SteamClient` APIs to detect game launch/exit events for our shortcut app IDs

Investigation needed to determine which is more reliable. Polling the process seems more direct; Steam tracking has better integration but may not fire reliably for non-Steam shortcuts.

### Save file locations (depends on Phase 4 preset):
- **RetroDECK**: `~/retrodeck/saves/{system}/{rom_name}.srm`, `~/retrodeck/states/{system}/`
- **EmuDeck**: `~/Emulation/saves/{system}/`, varies per standalone emulator
- **Manual**: User-configured save directory from Phase 4 settings
- **PCSX2 standalone**: `{saves_dir}/ps2/memcards/` (shared memory cards)
- **DuckStation standalone**: `{saves_dir}/psx/memcards/`
- Pattern: `{saves_base}/{system}/` for most systems — base path from settings

### Upload flow (after play session ends):
1. Detect game session ended (via chosen detection method)
2. Scan save directory for files newer than last sync timestamp
3. For each changed save file:
   - Compare `updated_at` from RomM save vs local file `mtime`
   - If local is newer → upload via `POST /api/saves` with `rom_id` and `emulator`
   - If remote is newer → conflict (see below)
   - If equal → skip

### Download flow (before play or on-demand):
1. Fetch saves: `GET /api/saves?rom_id={id}`
2. Compare each save's `updated_at` with local file `mtime`
3. Download newer saves via `GET /api/saves/{id}/content`
4. Place in correct RetroDECK save directory

### Conflict resolution options (user setting):
- **"Always upload local"**: Local saves win. Upload even if remote is newer.
- **"Always download remote"**: Remote wins. Overwrite local.
- **"Ask me"** (default): Show conflict dialog in QAM with timestamps, let user choose.
- **"Newest wins"**: Compare timestamps, use whichever is more recent.

### Auto-sync behavior options:
- **Sync saves before launch** (toggle, default: on): Download latest saves before starting game
- **Sync saves after play** (toggle, default: on): Upload changed saves after game exits
- **Background periodic sync** (toggle, default: off): Sync all saves every N minutes

### Save sync tracking:
- Track per-rom last sync timestamp in state.json
- Track which emulator created each save (RomM's `emulator` field)
- Handle multiple save files per game (e.g. multiple memory card slots)

### Manual "Sync All Saves to RomM" button:
- In Danger Zone (or Save Sync settings page): one-click button to upload all local saves to RomM
- Scans all installed ROMs, finds their save files, uploads any that are newer than RomM's copy
- Use case: before uninstalling all ROMs, user can ensure saves are backed up to RomM
- Also useful as a manual "backup my saves" action independent of play sessions

### QAM UI additions:
- **Save Sync settings sub-page**: Conflict resolution mode, auto-sync toggles, sync interval
- **Per-game save status on game detail page**: Last synced, local/remote timestamps, manual sync button
- **Conflict dialog**: Show when "Ask me" mode encounters a conflict
- **"Sync All Saves to RomM" button**: In Danger Zone, uploads all local saves before destructive actions

### Verification:
- [ ] Save file uploaded to RomM after play session
- [ ] Save file downloaded from RomM before launch
- [ ] Conflict detected and presented to user
- [ ] "Newest wins" correctly compares timestamps
- [ ] Multiple save files for same game handled
- [ ] Save sync works across different emulators for same system
- [ ] Save sync status visible on game detail page

## Phase 5.5: Sync Progress & Cancel — Bug Fixes

**Goal**: Fix two non-functional features: the sync progress bar and cancel sync button.

**Status**: Not working despite multiple fix attempts. Requires deeper investigation.

### Bug 1: Sync Progress Bar Not Updating

**Symptom**: Progress bar appears briefly (indeterminate), then either freezes or disappears. Does not show real-time progress during sync. The sync itself completes successfully — only the UI feedback is broken.

**What was tried (all failed)**:
1. Setting initial `syncProgress` immediately in `handleSync()` before `await startSync()`
2. Changing backend `finally` block to not emit `running: false` prematurely (added 60s safety timeout)
3. Adding `updateApplyProgress` callable for frontend to report per-item progress back to backend
4. **Event-based approach**: Backend emits `sync_progress` events via `decky.emit()`, persistent listener in `index.tsx` writes to module-level store, MainPage polls store at 250ms — no WebSocket round-trips

**Current architecture** (as implemented but not working):
- `syncProgress.ts`: Module-level variable store (`_progress`), updated by event listener + syncManager
- `index.tsx`: Persistent `sync_progress` event listener calls `setSyncProgress()` on the module store
- `syncManager.ts`: Calls `updateSyncProgress()` per shortcut during the applying phase
- `MainPage.tsx`: `setInterval(250ms)` reads `getSyncProgress()` from module store, updates React state

**Research findings**:
- QAM panel **unmounts** `MainPage` when closed, destroying all React state and intervals. On reopen, MainPage remounts fresh — this is handled by checking the store on mount.
- Decky's WebSocket bridge has contention: concurrent `callable()` calls (e.g. `getArtworkBase64()` during sync) may block or delay other calls.
- The module-level store approach should bypass WebSocket contention since it's a plain JS read, but progress still doesn't update.

**Investigation needed**:
- Verify `sync_progress` events are actually being received by the frontend (add `console.log` in event listener)
- Verify the `setInterval` in MainPage is actually running and reading updated values
- Check if `setSyncProgress` in the event listener is being called with correct data
- Check if `updateSyncProgress` in syncManager is being called (the applying phase runs entirely in frontend)
- Consider whether the 250ms polling interval is too slow or if React batching is preventing re-renders
- Test with a minimal reproduction: hardcode progress updates on a timer to isolate whether the issue is data flow or rendering

### Bug 2: Cancel Sync Not Working

**Symptom**: Clicking "Cancel Sync" does not stop the frontend shortcut processing loop. Backend cancellation may work (stops ROM fetching), but the frontend `sync_apply` handler continues processing all shortcuts.

**Current implementation**:
- `syncManager.ts`: Module-level `_cancelRequested` flag, checked after each shortcut in the loop
- `MainPage.tsx`: `handleCancel()` calls both `requestSyncCancel()` (sets frontend flag) and `cancelSync()` (backend callable)
- Backend `cancelSync()`: Sets `_sync_cancel = True` in Python, which stops the backend sync loop

**Why it might not work**:
- The `sync_apply` event is fired ONCE with all shortcut data. By the time the user clicks cancel, the backend has already emitted the full payload. Backend cancellation only helps if the backend is still fetching ROMs.
- The frontend cancel flag (`_cancelRequested`) should work for the frontend loop, but may not be checked if the loop is blocked on an `await` (e.g. `addShortcut()` or `getArtworkBase64()`)
- Need to verify `requestSyncCancel()` is actually being called and the flag is being read

**Investigation needed**:
- Add `console.log` to verify `requestSyncCancel()` is called
- Add `console.log` inside the sync loop to verify the flag check runs
- Check if the `await getArtworkBase64()` call is blocking for a long time, preventing the cancel check
- Consider adding the cancel check BEFORE the artwork fetch (currently only checked at end of loop iteration)
- Consider whether a different cancellation mechanism is needed (e.g. AbortController for fetch calls)

### Bug 3: RomM M3U Lists BIN Files Instead of CUE

**Symptom**: RomM's download endpoint auto-generates M3U files for multi-file ROMs. For single-disc multi-track games (e.g. Tomb Raider), the M3U lists all `.bin` tracks + the `.cue` file. This is wrong — the M3U should only list `.cue` files (for multi-disc switching). The CUE file already references its BIN tracks internally.

**Impact**: Our `_detect_launch_file` prefers M3U over CUE. So RetroArch gets an M3U pointing to raw BIN files instead of the proper CUE sheet. Audio tracks won't play correctly.

**Fix**: After extraction, validate downloaded M3U files. If an M3U contains only `.bin` entries (plus optionally one `.cue`), it's a bad single-disc M3U — delete it. A proper multi-disc M3U lists `.cue`/`.chd`/`.iso` entries. Alternatively, fix `_detect_launch_file` to prefer CUE over M3U when the M3U only contains `.bin` files.

### Verification:
- [ ] Progress bar shows real-time progress during sync (e.g. "Applying 5/45: Game Name")
- [ ] Progress bar shows collection creation progress
- [ ] Cancel button stops the sync mid-progress
- [ ] Partial results are saved after cancellation
- [ ] Progress bar works correctly even if QAM is closed and reopened during sync
- [ ] Single-disc multi-track game (e.g. Tomb Raider) launches via CUE, not bad M3U

---

## Phase 6: Polish + Advanced Features

**Goal**: Production-ready with good UX and reliability.

### Multi-version / multi-language ROM selector:
- When multiple versions of the same game exist in RomM (e.g. USA, Europe, Japan), show a version dropdown on the game detail page before downloading
- RomM groups versions via `siblings` field (matched by shared igdb_id on same platform)
- **Caveat**: RomM's sibling matching has known bugs — groups numbered sequels as siblings (e.g. Gran Turismo 1+2, Pokemon Black+Black 2). See rommapp/romm#1959.
- Each ROM has `regions`, `languages`, `revision`, `tags` fields parsed from filename
- Implementation: on game detail page, if ROM has siblings, show dropdown with region/language info before download
- Option to "Download all versions" — downloads all siblings, then a second dropdown selects which version gets launched (stored in `installed_roms` per rom_id)
- Only relevant when user has multiple regional versions in RomM — low priority

### Auto sync interval:
- Configurable in settings (off / 1h / 6h / 12h / 24h / on plugin load)
- Background task in `_main()` that triggers `_do_sync()` on interval
- Toast notification on completion
- Skip if sync already running or no connection

### Library management improvements:
- Re-sync preserves installed state and save sync timestamps
- Detect ROMs removed from RomM → prompt to remove local shortcut + files
- Detect ROMs updated on RomM → flag for re-download
- Stale state cleanup on startup (see "State Consistency / Startup Pruning" below)

### State Consistency / Startup Pruning:

**Problem**: We use a flat `state.json` file (with atomic `os.replace()` writes) to track `shortcut_registry` and `installed_roms`. If Steam crashes mid-sync, the plugin crashes mid-download, or the user force-closes during operations, state can drift from reality:

- `installed_roms` entry exists but the ROM file is gone from disk
- `shortcut_registry` entry exists but the Steam shortcut no longer exists
- ROM file exists on disk but no `installed_roms` entry tracks it (orphaned partial download)
- Single-file downloads lack `.tmp` atomicity (multi-file ZIP downloads already use `.zip.tmp` → rename)

**Note**: We do NOT use SQLite — just flat JSON with atomic writes via `os.replace()`. This is fine for our scale, but startup healing is essential to prevent state drift from accumulating.

**Solution — startup state healing in `_main()`**:

1. **Prune `installed_roms`**: Iterate entries, remove any where `file_path` no longer exists on disk.
2. **Prune `shortcut_registry`**: Frontend checks which Steam shortcuts still exist via `SteamClient` API, reports stale app IDs back to backend. Backend removes orphaned registry entries.
3. **Download atomicity**: Single-file ROM downloads should write to `{file_path}.tmp` and `os.replace()` to final path on completion (matching the existing multi-file pattern). This prevents partial files from being mistaken for complete downloads.
4. **Save state after pruning**: Write the cleaned state back to `state.json` before normal operation begins.

The frontend-to-backend round-trip for step 2 follows the same pattern as `reportSyncResults()` — frontend enumerates existing shortcuts and sends a list back.

### Rename project to "RomM Deck":
- Rename GitHub repo from `romm-library` to `romm-deck`
- Update `package.json`, `plugin.json`, `release-please-config.json`
- Update all code references: `main.py`, `bin/romm-launcher`, `src/index.tsx`, `src/components/GameDetailPanel.tsx`
- Update `CLAUDE.md`
- Update Decky plugin directory paths in launcher (`homebrew/plugins/romm-library` → `romm-deck`)
- Update git remote URL
- **Do this before first public release** — breaks existing installs

### Documentation:
- **README.md**: Setup guide, features, screenshots, requirements
- **RomM account warning**: Document that users should use their own RomM account (not shared/generic) so save games are correctly attributed per user
- **BIOS setup guide**: How to upload BIOS files to RomM, then download through the plugin
- **Emulator preset guide**: Differences between RetroDECK, EmuDeck, and manual setup

### Offline mode:
- Cache platform and ROM lists locally
- Graceful degradation when RomM unreachable
- Queue operations for when connection returns

### Stacked sync progress UI:
Replace the single progress bar with a stacked phase list. Each phase appears as a new line:
1. **Fetching platforms** — spinner while running, then checkmark when done (stays visible)
2. **Fetching ROMs** — appears below, progress bar (e.g. 3/12 platforms), checkmark when done
3. **Downloading artwork** — appears below, progress bar (e.g. 15/45 ROMs), checkmark when done
4. **Applying shortcuts** — appears below, progress bar (e.g. 8/45), checkmark when done
5. **Creating collections** — appears below, progress bar (e.g. 3/7), checkmark when done
6. **Done** — final checkmark

Each completed phase stays visible with a checkmark so the user sees the full pipeline. Requires replacing `ProgressBarWithInfo` with a custom component that accumulates phase state. Backend needs to emit phase transitions (not just overwrite `_sync_progress`). Frontend needs a list of `{ phase, status: "running"|"done", current, total, message }`.

### Error handling:
- Comprehensive error handling for all API calls
- Download retry with exponential backoff
- Toast notifications for all errors
- Detailed logging for debugging

### CI/CD:
- Build job in release.yml: pnpm build, vendor py_modules, package ZIP
- Upload as GitHub release asset via release-please
- Automated testing in CI

### Final verification (full smoke test):
- [ ] Plugin loads in Decky without errors
- [ ] RomM connection succeeds with valid credentials
- [ ] Sync populates Steam Library with all RomM games (instant, no restart)
- [ ] Cover art visible on game tiles
- [ ] Games in correct platform collections
- [ ] Download starts from game detail page (single file)
- [ ] Multi-disc download extracts and creates M3U
- [ ] Storage space check works
- [ ] Progress visible in QAM and game detail
- [ ] Downloaded ROM in correct RetroDECK directory
- [ ] Play launches RetroDECK with correct system and emulator
- [ ] Emulator override works per-system and per-game
- [ ] Save files sync up to RomM after play
- [ ] Save files sync down from RomM before play
- [ ] Save conflict resolution works
- [ ] Uninstall removes ROM and updates status (instant, no restart)
- [ ] Library cleanup removes only our shortcuts (instant)
- [ ] Remove All Non-Steam Games respects whitelist
- [ ] Uninstall All removes ROM files, warns about saves
- [ ] Manual save sync uploads all local saves to RomM
- [ ] Re-sync preserves existing state
- [ ] Auto sync interval works
- [ ] Plugin survives Steam/Decky restart
- [ ] Offline mode degrades gracefully

---

## Future Improvements (nice-to-have)

- **Concurrent download queue**: Support multiple queued downloads instead of one at a time. Better UX but needs resource management.
- **RomM native device sync**: When RomM v4.7+ ships device sync features (slots, conflict detection, `device_id` tracking), migrate from our own conflict resolution to RomM's native implementation. Track this in RomM release notes.
- **Game descriptions/metadata**: Inject ROM summary, genres, screenshots from RomM metadata into Steam game detail page.
- **Download queue priority/reordering**: Let users reorder queued downloads.

## Known Issues to Investigate

- **Shared memory cards (PS1/PS2)**: These systems use shared memory cards rather than per-game saves. Need to determine how to associate uploads with specific ROMs, or handle at a system level. Will be addressed during Phase 5 implementation.
- **Play session detection reliability**: Need to compare polling RetroDECK process vs Steam play tracking. Will prototype both during Phase 5.
