# decky-romm-sync — Implementation Plan

Forward-looking roadmap. Completed phases are summarized at the bottom.
Reference material (API tables, architecture, environment) lives in CLAUDE.md.

---

## Phase R1: Architecture Foundation

**Goal**: Establish the new backend architecture (composition + service layer + adapters) as a foundation for Phase 8 and all future work. See `docs/architecture.md` for full design.

**Steps:**
1. Create directory structure (`models/`, `services/`, `adapters/`)
2. Define domain dataclasses (`models.py`, `settings.py`, `state.py`) — typed replacements for raw dicts
3. Extract `persistence.py` from `StateMixin` (load/save settings, state, caches)
4. Extract `RommHttpClient` from `RommClientMixin` (generic HTTP, SSL, auth, retry)
5. Write `bootstrap.py` skeleton — composition root called from `_main()`
6. `main.py` starts using bootstrap but still has mixins for unmigrated services

**Constraints:**
- All 805+ existing tests must keep passing throughout
- Each step is a mergeable PR
- Unmigrated mixins coexist with new services during transition
---

## Phase 8: Save Sync v2 — RomM 4.7.0 Migration (includes Phase R2)

**Goal**: Migrate save sync to RomM 4.7.0's device-based sync architecture. Simplify conflict detection, remove workarounds for 4.6.1 bugs. Simultaneously migrate save sync to the new architecture (Phase R2 from `docs/architecture.md`).

### Key RomM 4.7.0 Changes

**Device registration:**
- `POST /api/devices` — register with hostname/MAC fingerprint, returns `device_id`
- Pass `device_id` on all save operations for proper sync tracking
- Replace our hostname-based `register_device()` with RomM's native device API

**Save endpoint improvements:**
- `GET /api/saves/{id}/content` **now works** — remove `download_path` workaround
- `content_hash` in SaveSchema — remove download-and-hash workaround
- `POST /api/saves` returns **409 Conflict** on stale sync — server-side conflict detection
- `device_syncs[]` array per save — per-device sync status tracking
- New endpoints: `POST /api/saves/{id}/track`, `POST /api/saves/{id}/untrack`
- Slot support: `slot` parameter on save endpoints
- Bulk delete: `POST /api/saves/delete` with ID list

**Backwards compatibility strategy:**
Not all users upgrade RomM at the same time. Hard-requiring 4.7.0 would break existing users.

- **Version detection**: On connection test / first sync, probe RomM API version (check for 4.7.0 device endpoints — `GET /api/devices` returns 200 vs 404/405). Cache detected version.
- **Dual-path approach**: Keep existing 4.6.x save sync code as fallback. When RomM ≥ 4.7.0 detected, use new device-based endpoints. When < 4.7.0, use current workarounds.
- **Graceful degradation**: Features that require 4.7.0 (device registration, server-side conflict detection, `content_hash`) simply don't activate on older servers. Core save sync still works.
- **Settings indicator**: Show RomM version in connection settings. If < 4.7.0, show info note: "Upgrade RomM to 4.7.0+ for improved save sync."
- **Migration timeline**: After ~2-3 releases with dual support, consider dropping 4.6.x support with a deprecation notice in release notes.

**Migration plan (4.7.0 path):**
1. Add RomM version detection to connection test
2. Register device via `POST /api/devices` (replace custom device registration)
3. Use `content_hash` from save responses (remove `_get_server_save_hash()` download-and-hash)
4. Use `GET /api/saves/{id}/content` directly (remove `download_path` URL construction)
5. Handle 409 responses from `POST /api/saves` as conflict signal (complement client-side detection)
6. Track device sync status via `device_syncs[]` (know which devices are in sync)
7. Consider removing `pending_conflicts` persistence (see save sync conflict architecture refactor in Future Improvements)

**Other 4.7.0 features to leverage:**
- `last_played` auto-updated on save upload — could complement our playtime tracking
- `RomUserSchema` fields: `backlogged`, `now_playing`, `hidden`, `rating`, `completion`, `status` — future UI features
- New ROM identifier fields: `moby_id`, `ss_id`, `hltb_id`, `launchbox_id` — future metadata enrichment

---

## Phase 9: Multi-Emulator Support (Deferred)

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

## Phase 10: Polish & Advanced Features (Deferred)

- **Multi-version/language ROM selector**: Dropdown when multiple versions exist
- **Auto sync interval**: Configurable background re-sync
- **Library management**: Detect removed/updated ROMs, stale state cleanup
- **Offline mode**: Cache lists locally, queue operations
- **Error handling**: Retry with backoff, toast notifications, detailed logging. ~~Frontend error differentiation~~: ✅ Done — `classify_error()`/`error_response()` in `errors.py` maps structured exceptions to user-friendly messages and `error_code` fields. All backend callables (`test_connection`, `start_download`, `_do_sync`, firmware, save sync) return `{success, message, error_code}`. Frontend `BackendResult` type with `RommErrorCode` union. Users now see "Authentication failed", "Server unreachable", "SSL certificate error", etc. instead of generic messages
- ~~**Connection settings UX**: Remove save button, save on popup confirm~~ ✅ Done — auto-save on modal confirm, Save Settings button removed
- **RomM playtime API**: When feature request #1225 ships, plug in delta-based accumulation
- **Emulator save state sync**: RetroArch `.state` files (larger, version-specific, multiple slots)
- **Steam gear menu**: Add to Favorites, Collections, Hide Game, etc.
- **Save backup on enable**: Prompt to create local save backup when toggling save sync on, and as option during conflict resolution
- **Screenshots gallery**: Custom IGDB screenshot gallery in game detail (deferred from Phase 4C)
- ~~**Sync preview / dry-run**: Show "X shortcuts to add, Y to remove, Z unchanged" before applying. Let user review changes before committing the sync.~~ ✅ Done — delta sync with preview before apply (#76)
- **Insecure SSL warning prominence**: Current toggle has a text description but no visual warning styling. Add warning icon/color and consider a confirmation dialog when enabling, since it allows MITM.

---

## External Review Findings

Items from a full code review of `main` and `feat/phase-5-save-sync` branches. New items not tracked elsewhere:

### EXT-1: Platform Map Caching ✅
`_resolve_system()` now caches `_platform_map` on first call via `hasattr` check. No repeated disk reads.

### EXT-2: Atomic Writes for Settings ✅
All state/settings writes use atomic `.tmp` + `os.replace()` pattern.

### EXT-3: Download Queue Memory Growth ✅
`_prune_download_queue()` keeps max 50 terminal items (completed/failed/cancelled), called after each download. `clear_completed_downloads()` callable lets frontend clear on demand.

### EXT-4: HTTP Client Code Duplication ✅
Consolidated into `_romm_ssl_context()` + `_romm_auth_header()` helpers in `romm_client.py`. Moved RomM HTTP methods from `save_sync.py` to `romm_client.py`.

### EXT-5: Blocking I/O in Async Callables ✅
All HIGH/MEDIUM severity blocking I/O wrapped in `run_in_executor`: `save_sync.get_save_status` (conflict detection + hashing), `downloads._do_download` (ZIP extraction, M3U gen, file renames), `downloads._poll_download_requests` (fcntl lock), `downloads.remove_rom`/`uninstall_all_roms`, `sync.report_sync_results`/`report_removal_results` (artwork renames + VDF writes), `sgdb.verify_sgdb_api_key` (resp.read on event loop), `main.migrate_retrodeck_files`/`get_migration_status` (FS traversal), `main.set_system_core`/`set_game_core` (XML I/O), `firmware.download_firmware` (MD5 hash), `firmware.delete_platform_bios`. Remaining LOW items (single small state file writes) are <10ms and deferred.

### EXT-6: Shell Interpolation in Launcher
`bin/romm-launcher` interpolates `$ROM_ID` into Python strings. Regex-validated (digits only) so safe, but fragile. Consider environment variables instead.

### EXT-7: No Rate Limiting on RomM API During Sync
Rapid sequential requests during batch sync. Add configurable delay for remote/slow servers.

### EXT-8: Structured HTTP Error Handling in RomM Client ✅
Exception hierarchy in `lib/errors.py`: `RommApiError` base → `RommAuthError` (401), `RommForbiddenError` (403), `RommNotFoundError` (404), `RommConflictError` (409), `RommServerError` (5xx), `RommConnectionError`, `RommTimeoutError`, `RommSSLError`. All `_romm_*` methods in `romm_client.py` translate urllib exceptions via `_translate_http_error()`. Handles URLError-wrapped SSL/timeout, subclass ordering (HTTPError before URLError, ssl before OSError). Callers can catch specific types or continue catching generic `Exception`.

### EXT-9: File Locking on State Files
`fcntl.flock()` is used for `download_requests.json` but NOT for `state.json`, `settings.json`, `metadata_cache.json`, or `save_sync_state.json`. Decky plugin loader can trigger parallel calls — concurrent writes without locking risk corruption even with atomic writes.

### EXT-10: State File Schema Versioning
Only `save_sync_state.json` has a `"version"` field. `state.json`, `settings.json`, and `metadata_cache.json` lack schema versioning. Add version numbers + migration logic to handle format changes across plugin updates.

### EXT-11: Generalize `_with_retry` to RomM Client ✅
`_with_retry()` and `_is_retryable()` moved from `SaveSyncMixin` to `RommClientMixin`. Retry logic updated to use structured exceptions: `RommServerError`, `RommConnectionError`, `RommTimeoutError` are retryable; auth/forbidden/not-found/conflict/SSL are not. All existing save_sync callers work unchanged via MRO. `save_sync.py` 409 handler updated to catch `RommConflictError` instead of manual `HTTPError.code` check.

---

## Future Improvements (nice-to-have)

- **Concurrent download queue**: Multiple queued downloads
- ~~**RomM native device sync**~~: → Promoted to Phase 8
- **Download queue priority/reordering**
- **Developer vs Publisher distinction**: RomM's `companies` is flat — research IGDB's `involved_companies` relationship for proper split
- **Sync completion notification accuracy**: Track new vs updated vs unchanged shortcuts, show accurate breakdown (cancel notifications already show correct count)
- **Library home playtime display**: Non-Steam shortcuts show "Never Played" despite tracked playtime. Steam doesn't persist `minutes_playtime_forever` for shortcuts. No known solution — all similar plugins have same limitation. Our game detail page shows accurate playtime.
- **Playtime sync between RomM and Steam**: Bidirectional cross-device playtime merging
- **Boot-time server playtime fetch**: `get_all_playtime()` at plugin load reads local state only. If a second device uploaded playtime since last boot, Steam shows stale local totals until next session end triggers a sync. Fix: fetch server playtime on boot and merge with local before applying to Steam UI.
- **UI settings page**: Machine-scoped collections toggle, device labels toggle, custom device name
- **Per-game sync selection**: Select/deselect individual games within a platform
- **Translations / i18n**: Adapt to user's Steam language (reference: Unifideck `src/i18n/`)
- **Global launch interceptor**: Safety net via `SteamClient.Apps.RegisterForGameActionStart` for launches from context menus/search/recent games (outside game detail page). Currently save sync and conflict checks only run when launching from the game detail page.
- ~~**Async/blocking audit**~~: ✅ Done (EXT-5). All HIGH/MEDIUM severity items fixed. Remaining: LOW-priority single-file state writes (`_save_state`, `_save_settings_to_disk`, `_save_metadata_cache`) are <10ms each and not worth the churn.
- **Save sync conflict architecture refactor**: Remove `pending_conflicts` persistence from `save_sync_state.json` in favor of fully live conflict detection. Currently conflicts are detected live (hash + timestamp) but then stored to disk and looked up later during resolution — this creates stale state risks and unnecessary complexity. Proposed changes:
  1. **Drop `pending_conflicts` from state file.** Every entry point (pre-launch, post-exit, manual sync, lightweight check) already does live detection. No need to persist between detections.
  2. **Derive `server_save_id` at resolution time.** Instead of storing it at detection time, `resolve_conflict()` should list saves for the ROM via API and match by filename. Eliminates the main reason for persistence.
  3. **Lightweight check should show "Possible Conflict"** instead of "Conflict" — it only compares timestamps/sizes, not hashes. Full confirmation happens on Play click. Avoids false positives scaring users.
  4. **Gear menu "Sync Saves" should show conflict modal.** Currently `syncRomSaves()` silently queues conflicts without user notification. Should behave like pre-launch sync: detect conflict → show modal → resolve or skip. Same for "Sync Saves" in SaveSyncSettings QAM page.
  5. **Pass conflict data through frontend round-trip.** `preLaunchSync()` already returns full conflict details (sizes, timestamps, server_save_id). Frontend shows modal, user picks resolution, frontend passes details back to `resolve_conflict()`. No backend state lookup needed.
- **Save sync: RetroArch save sorting support**: Currently hardcoded to `<saves_dir>/<system>/<rom>.srm` (matches RetroDECK default: `sort_savefiles_by_content_enable=true`, `sort_savefiles_enable=false`). Breaks silently if user enables "Sort by Core Name" (`<saves_dir>/<core_name>/` or `<saves_dir>/<system>/<core_name>/`), or disables both (flat `<saves_dir>/`). Options: (a) read RetroArch's `retroarch.cfg` to detect active sort mode and construct paths accordingly, (b) search multiple candidate paths, (c) refuse to enable save sync if non-default sort settings detected. Also affects multi-disc ROMs in subdirectories where content_dir becomes the ROM's subfolder name instead of the system name. Disclaimer added to enable-sync modal and wiki Save-Sync page.
- **Multi-save-file support**: Current logic assumes one `.srm` per ROM (RetroArch pattern). RomM's API supports multiple saves per ROM (different slots, emulators, devices). Locally, standalone emulators like PCSX2/Dolphin use shared memory cards or per-slot saves. Filename matching works for 1:1 but breaks with multiple files. Needs: enumerate all local + server saves per ROM, match by filename, detect conflicts per file, resolve individually or batch. Ties into Phase 7 standalone emulator save sync.
- **SGDB artwork disambiguation**: SGDB lookups can return wrong artwork for games with identical names across different releases (e.g. "Tomb Raider" 1996 vs 2013 reboot). Current flow: `sgdb_id` from RomM → download, or `igdb_id` → SGDB game lookup → download. If RomM's `sgdb_id` maps to the wrong game, or SGDB's IGDB mapping is inaccurate, wrong artwork is pulled. Potential fixes: (a) use release year from RomM metadata as disambiguation when SGDB returns multiple candidates, (b) prefer IGDB ID lookups over direct SGDB ID when both available, (c) add manual artwork override per game in the game detail page, (d) show artwork preview before applying so user can reject mismatches.
- **Artwork cache size cap**: Artwork files cached to disk with no size limit or eviction policy. Only cleanup is orphan pruning after sync. For large libraries (1000+ ROMs × 4 artwork types), unbounded disk usage could be problematic on Steam Deck. Add LRU eviction or configurable size cap.
- **CI: Decky build smoke test on PRs**: Decky CLI plugin build only runs during release workflow, not on PRs. A packaging regression won't surface until release time. Add decky build step to CI.
- **CI: Decky CLI SHA256 verification**: `release.yml` downloads decky CLI via plain curl with no integrity check. Pin a SHA256 hash and verify after download.
- **RomM M3U validation**: RomM bundles M3U files in ZIP archives that may list `.bin` track files (e.g. Tomb Raider lists 57 `.bin` tracks + 1 `.cue`). RetroArch expects M3U to list `.cue` files only. Need to test whether these RomM-bundled M3Us actually break launching. If they do: post-extraction validation to strip `.bin` entries or delete bad M3Us. If they work: drop this item. Our own `_maybe_generate_m3u()` is correct (only writes `.cue`/`.chd`/`.iso` entries).
- **Async race in sessionManager**: `handleGameStart`/`handleGameStop` are async but `RegisterForAppLifetimeNotifications` doesn't await them. Rapid start+stop could interleave, potentially losing playtime or corrupting session state. Fix: queue or serialize game lifecycle events.
- **retrodeck_config.py reads disk every call**: `get_saves_path()` → `get_retrodeck_path()` → `open()` + `json.load()` on every invocation. 50-ROM save sync = 50 reads of the same file. Fix: TTL cache (30s).
- **es_de_config.py cache never invalidates on external changes**: `_es_systems_cache` and `_core_defaults_cache` load once, only reset via `_reset_cache()` after `set_system_core`/`set_game_core`. If user changes core in ES-DE directly, plugin shows stale data until restart. Fix: mtime-based invalidation or TTL.
- **Deep tree dump floods backend at debug level**: `deepTreeDump()` runs for every RomM AppId on plugin load via `debugLog` callable. 100+ shortcuts at debug level hammers startup. Fix: gate behind flag, or run for one AppId per session only.
- **Cleared downloads hidden on re-download**: `cleared` Set in DownloadQueue React state persists rom_ids. Re-downloading a previously cleared ROM hides the new progress. Fix: clear rom_id from `cleared` when new `download_progress` event arrives.
- **Connection state via custom events, not central store**: Different components can have different connection states due to event propagation timing. Not a bug today, but a consistency risk. Fix (future): EventEmitter or subscriber-pattern store.
- **Test coverage gaps in es_de_config write paths**: Read operations well-covered, but write paths (`set_system_override`, `set_game_override`, `_rebuild_game_xml`) and the 4-stage core resolution chain need more edge-case coverage.
- **Dead code: `save_steamgriddb_key()`** in `lib/sgdb.py` — duplicate of `save_sgdb_api_key()`, never called from frontend. Delete it.
- **XML parsing duplication in es_de_config.py**: Four separate SAX parser implementations with own state management. A shared base parser class could save 100-150 lines. Refactoring candidate when code is stable.

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

### Phase 6: Bug Fixes & Stability ✅
**Bugs 4-8, 10-12** all resolved. State consistency/startup pruning, SSL verification, settings permissions (0600), BIOS status reporting (553-entry registry with required/optional/hash validation), RetroDECK path resolution (SD card support, migration UI), per-core BIOS filtering (expat-based ES-DE config parser, core_defaults.json fallback).
**Phase A — Per-core BIOS filtering**: Registry v4.0.0 with per-core `required` status. Active core resolution chain: per-game gamelist.xml → per-system gamelist.xml → live es_systems.xml → shipped core_defaults.json. BIOS detail shows all platform files with per-core annotations (one line per emulator). Dot colors: green=downloaded, red=missing+required by active core, orange=required by other core, grey=optional.
**Phase B — Core switching UI**: Per-game CPU button (microchip icon) + per-platform dropdown in BiosManager. Writes to ES-DE gamelist.xml. Live UI updates via `core_changed` events. BiosManager works offline. Per-game override always writes explicit label (avoids confusion with platform overrides).

### QAM Menu Restructuring ✅
7 pages consolidated to 4. **Settings**: absorbs SaveSyncSettings + Log Level + RetroArch fix, auto-save connection fields. **Platforms**: Sync/BIOS tab toggle, BIOS lazy-loaded. **Data Management**: 3 per-platform lists merged into 1 with action modal. **MainPage**: inline downloads, 3 nav buttons (down from 6), consolidated RetroArch warning. Delta sync with preview before apply. Consistent sync progress display: spinner during preview, `[step/total] Description X/Y` progress bar during apply with dynamic step counting.

### Phase 7: RetroAchievements + Game Detail Tabs ✅
**7A — Backend**: `achievements.py` module with `get_achievements`, `get_achievement_progress`, `sync_achievements_after_session` callables. `ra_id` extracted during sync and stored in shortcut registry. Achievement caching with 24h TTL (definitions) and 1h TTL (user progress). `get_cached_game_detail()` extended with `ra_id` + achievement summary.
**7B — QAM Settings**: Skipped — RA username auto-fetched from RomM user profile (`/api/users/me`), no manual configuration needed.
**7C — Tabbed Layout**: Game detail page restructured into tabbed layout (GAME INFO | ACHIEVEMENTS | SAVES | BIOS) in `RomMGameInfoPanel.tsx`. Tab visibility conditional on `ra_id`, save sync enabled, BIOS status. `romm_tab_switch` custom event for cross-component tab switching.
**7D — Achievement Badge**: Trophy badge in PlaySection info row showing earned/total with gold sparkle animation. Clickable to switch to achievements tab. Data from cached achievement summary.
**7E — Achievements Tab**: Full achievement list with progress bar, earned/locked sections, badge images (greyed for locked), hardcore indicator with sparkles, earned dates, points, rarity labels. Sorted earned-first then by display_order. Lazy-loaded on tab activation. 65 backend tests in `test_achievements.py`.
