# decky-romm-sync — Implementation Plan

Forward-looking roadmap. Completed phases are summarized at the bottom.
Reference material (API tables, architecture, environment) lives in CLAUDE.md.

---

## Phase 6: Bug Fixes & Stability — NEXT

**Goal**: Fix known bugs and improve reliability before adding more features.

### Bug 4: State Consistency / Startup Pruning ✅
Startup state healing implemented and tested — atomic settings, orphan cleanup, tmp pruning.

### Bug 5: SSL Certificate Verification ✅
SSL verification enabled for all requests. SteamGridDB always verifies via `certifi` CA bundle. RomM verifies by default with user toggle for self-signed certs. HTTP client consolidated (EXT-4).

### Bug 6: Secrets Stored in Plain Text ✅
`settings.json` enforces `0600` permissions on every write and on startup. OS keyring (D-Bus Secret Service) not viable — PluginLoader runs as root with no session bus. All other Decky plugins use plaintext JSON; `chmod 600` is the standard mitigation.

### Bug 7: BIOS Status Reporting ✅
Static BIOS registry (`defaults/bios_registry.json`) derived from libretro core-info + System.dat (553 entries, 51 platforms, v3.0.0). Backend enriches firmware responses with `required`/`description`/`hash_valid`/`classification` fields. Frontend distinguishes required vs optional vs unknown files in BiosManager, PlaySection badge, and GameInfoPanel. "Download Required" button for required-only downloads. Unknown files shown in orange with GitHub issue prompt. Platform-grouped registry with `firmware_path` field for correct subfolder placement.

### Bug 8: VDF-Created Shortcut Icons Not Displaying ✅
Icons display correctly. No issue found.

### Bug 10: BIOS Badge Missing from PlaySection ✅
`bios_status` was hardcoded to `None` in `get_cached_game_detail`. Now populated via `check_platform_bios()`.

### Bug 11: RetroDECK Path Resolution ✅
All file downloads (ROMs, BIOS) hardcoded to `~/retrodeck/` — breaks SD card installs. Now reads paths from `retrodeck.json` via centralized `lib/retrodeck_config.py`. BIOS subfolder placement from registry `firmware_path` (eliminates manual `BIOS_DEST_MAP`). BIOS download tracking in `state.json`. Path change detection on startup with migration UI (MainPage warning banner + ConnectionSettings migration panel). Untracked BIOS files matched by registry for migration.

### Bug 12: BIOS Required/Optional Per Active Core

Currently OR-logic across all cores — if ANY core marks a file required, it shows as required. This causes false warnings (e.g. GBA BIOS shown required because gpSP needs it, even though RetroDECK defaults to mGBA which doesn't). Also shows BIOS files from unrelated systems (e.g. GB/GBC/SGB BIOS on a GBA game page) because the registry entry includes all files any core on that platform could use.

**Research findings:**
- RetroDECK uses ES-DE's `es_systems.xml` for core defaults (first `<command>` = default). Baked into flatpak, accessible at predictable path under `/var/lib/flatpak/app/net.retrodeck.retrodeck/.../files/retrodeck/components/es-de/share/es-de/resources/systems/linux/es_systems.xml`.
- Users can override per-system via ES-DE menu (Other Settings > Alternative Emulators) — stored in `{retrodeck_home}/ES-DE/gamelists/{system}/gamelist.xml` as `<alternativeEmulator><label>...</label></alternativeEmulator>`.
- Users can override per-game via metadata editor — stored as `<altemulator>...</altemulator>` in game entry.
- Resolution chain: per-game override → per-system override → es_systems.xml default.
- Our `romm-launcher` calls `flatpak run net.retrodeck.retrodeck "$ROM_PATH"` — RetroDECK/ES-DE determines the core using the same resolution chain. Our games use whatever core ES-DE is configured to use.
- Games placed in `{retrodeck_home}/roms/{system}/` are auto-discovered by ES-DE.
- No `core_defaults.json` shipped — read es_systems.xml live instead.

#### Phase A: Read-Only BIOS Filtering (Bug 12 fix)

**Goal:** Show only the BIOS files relevant to the active core for each platform/game.

1. **Parse es_systems.xml live** — new `lib/es_de_config.py` module:
   - Find es_systems.xml in flatpak path (glob for version-independent matching)
   - Structural validation before parsing: root is `<systemList>`, each `<system>` has `<name>` and `<command label="...">`. If validation fails → log warning, fall back to current behavior (show all files)
   - Extract per-system: default core (first `<command>`), available cores list (all `<command>` entries with labels)
   - Parse gamelist.xml for per-system overrides (`<alternativeEmulator>`)
   - Parse gamelist.xml for per-game overrides (`<altemulator>`) — matched by ROM filename
   - Resolution: `get_active_core(system_slug, rom_filename=None)` → core label

2. **Restructure `bios_registry.json`** — per-core firmware requirements:
   - Current: `platforms > {slug} > {filename} > {required: bool}` (OR across all cores)
   - New: add `cores` dict to each file entry: `{core_label: {required: bool}}` mapping which cores need this file
   - Update `generate_bios_registry.py` to produce per-core data from libretro core-info
   - Keep top-level `required` as fallback (for unknown cores or validation failure)

3. **Filter in `check_platform_bios()`** — use active core to filter:
   - Call `get_active_core(platform_slug)` to determine active core
   - For each file in registry: check if the active core is in the file's `cores` dict
   - If active core not listed → file is irrelevant, skip it entirely
   - If listed → use that core's `required` value instead of the top-level OR value
   - Return `active_core` label in response so frontend can show it as a badge

4. **Frontend: show active core badge** — display which core is active on game detail page and BiosManager

5. **BiosManager (per-platform view):** Show default core's requirements only. If per-game overrides exist for different cores, show a note.

**Fallback:** If es_systems.xml can't be found or fails structural validation, fall back to current behavior (show all files with OR-logic). Log a warning.

#### Phase B: Core Switching UI (separate PR)

**Goal:** Let users change the active core per-platform and per-game from within the plugin, without leaving Game Mode.

1. **Per-platform core selector in BiosManager QAM page:**
   - Dropdown showing available cores (from es_systems.xml) for the platform
   - Current selection shows the active core (per-system override or default)
   - Changing writes `<alternativeEmulator><label>CoreName</label></alternativeEmulator>` to `{retrodeck_home}/ES-DE/gamelists/{system}/gamelist.xml`
   - Does NOT overwrite existing per-game overrides

2. **Per-game core selector in gear menu (game detail page):**
   - Dropdown in gear popup showing available cores for the game's platform
   - Current selection shows per-game override or "Platform default (CoreName)"
   - Changing writes `<altemulator>CoreName</altemulator>` to game entry in gamelist.xml

3. **Structural validation gate:** If es_systems.xml fails validation, disable core switching UI entirely. Show "Unsupported ES-DE version" message. Read-only BIOS filtering still works via fallback.

4. **BIOS display updates live** when core is changed — re-run `check_platform_bios()` after core switch.

### Testing needed
- [x] Startup pruning removes orphaned state entries
- [x] Shortcut icons display correctly in Steam
- [ ] BIOS files download to correct SD card path
- [ ] Migration moves files from internal to SD card
- [ ] BIOS required/optional matches active core (Bug 12)

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

### EXT-2: Atomic Writes for Settings ✅
All state/settings writes use atomic `.tmp` + `os.replace()` pattern.

### EXT-3: Download Queue Memory Growth
`_download_queue` grows indefinitely. Prune completed/failed entries after N days or max queue size.

### EXT-4: HTTP Client Code Duplication ✅
Consolidated into `_romm_ssl_context()` + `_romm_auth_header()` helpers in `romm_client.py`. Moved RomM HTTP methods from `save_sync.py` to `romm_client.py`.

### EXT-5: Blocking I/O in Async Callables — PARTIALLY FIXED
`save_sync.py` wrapped in `run_in_executor` (`_sync_rom_saves`, `_with_retry`, `_sync_playtime_to_romm`, `_resolve_conflict_io`). Same pattern likely exists in other modules — tracked in Future Improvements async/blocking audit.

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
- **Sync completion notification accuracy**: Track new vs updated vs unchanged shortcuts, show accurate breakdown (cancel notifications already show correct count)
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
- **RomM M3U validation**: RomM bundles M3U files in ZIP archives that may list `.bin` track files (e.g. Tomb Raider lists 57 `.bin` tracks + 1 `.cue`). RetroArch expects M3U to list `.cue` files only. Need to test whether these RomM-bundled M3Us actually break launching. If they do: post-extraction validation to strip `.bin` entries or delete bad M3Us. If they work: drop this item. Our own `_maybe_generate_m3u()` is correct (only writes `.cue`/`.chd`/`.iso` entries).

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

### Phase 5: Save File Sync ✅
Bidirectional `.srm` save sync between RetroDECK and RomM. Three-way conflict detection, four resolution modes (ask_me, newest_wins, always_upload, always_download). Pre-launch and post-exit sync, manual "Sync All Saves Now". Device registration, session detection, playtime tracking via RomM user notes. Native Steam playtime display. Conflict resolution popup. Save sync settings QAM page. Pre-launch toast notifications (success/failure). Shared account warning with orange styling. Blocking I/O wrapped in `run_in_executor`.

### Phase 5.6: Game Detail Page ✅
Custom game detail page for RomM games. RomMPlaySection with info items (Last Played, Playtime, Achievements, Save Sync, BIOS). RomMGameInfoPanel for metadata. CustomPlayButton with play/download/syncing/conflict/launching states + dropdown menu. Cache-first rendering via `get_cached_game_detail` callable. RomM Status badge (green/grey/blue). Lightweight save status check on page visit. Metadata TTL refresh (7-day stale check). SGDB artwork restore. Delete save/BIOS files. Live reactivity via `romm_data_changed` events. Frontend logging overhaul with log level system.

### Bug Fixes (pre-Phase 6) ✅
**Bug 1**: Sync progress bar — fixed nProgress range (0-100), heartbeat-based timeout, `[X/6]` step indicator, download progress in game detail button.
**Bug 2**: Cancel sync — wired `requestSyncCancel()` to frontend phases, toast shows correct count.
**Bug 9**: Play button first-click — dropped BIsModOrShortcut bypass, own entire game detail UI.
