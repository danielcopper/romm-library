# Pre-Beta Release Review — Consolidated

Merged findings from 5 automated review agents + manual review.
Items marked with source: `[manual]` = your review, `[agent]` = automated, `[both]` = found by both.

---

## MUST FIX before beta

### 1. Download request polling has no file lock `[agent]` -- FIXED
**File**: `lib/downloads.py:74-87`

`_poll_download_requests()` reads the request file and clears it without `fcntl` locking. `romm-launcher` writes with `LOCK_EX`. Between read and clear, a launcher write is lost.

**Fix**: Added `fcntl.LOCK_EX` around the read+clear, matching the launcher's pattern.

---

### 2. ConflictModal signals success on error `[agent]` -- FIXED
**File**: `src/components/ConflictModal.tsx:54-70`

If `resolveConflict()` throws, the catch block logs but still calls `closeModal()` + `onDone(resolution)`. Caller updates state as if conflict was resolved.

**Fix**: Added `return` after each `logError()` to prevent `onDone()` from being called on error.

---

### 3. CLAUDE.md is outdated `[both]` -- FIXED
**File**: `CLAUDE.md:72`

Says "Latest release: v0.7.0", actual is v0.9.1. "In progress" references Phase 5, but Phase 6 is complete. This is the onboarding doc for contributors and AI assistants.

**Fix**: Updated version, phase status, test count, and file structure section.

---

### 4. `_load_platform_map()` reads from disk every call — EXT-1 `[manual]` -- FIXED
**File**: `lib/romm_client.py:30-41`

`_resolve_system()` calls `_load_platform_map()` which does `open()` → `json.load()` on every invocation. 500-ROM sync = 500 disk reads of `defaults/config.json`.

**Fix**: Lazy-init cache via `hasattr(self, '_platform_map')` in `_resolve_system()`.

---

### 5. Wiki save sync architecture is wrong `[agent]` -- FIXED
**Files**: `Save-File-Sync-Architecture.md` vs `lib/save_sync.py`

Multiple discrepancies:
- Clock skew tolerance: wiki says 5s, code is 60s (line 56)
- Field names: wiki says `last_snapshot_hash`/`last_synced_at`, code uses `last_sync_hash`/`last_sync_at`
- Structure: wiki shows flat per-ROM, code nests under `files[filename]`
- Pre-launch trigger: wiki says automatic via RegisterForAppLifetimeNotifications, code does it manually from CustomPlayButton.handlePlay
- Conflict payload: wiki says `file_path`, code uses `filename` + `local_path`
- Playtime: wiki shows under `saves.<id>.playtime_seconds`, code has separate top-level `playtime` section

**Fix**: Rewrite the wiki's schema section, trigger description, and field reference to match code.

---

## SHOULD FIX before beta

### 6. gameDetailPatch plugin detection is fragile `[manual]` -- FIXED
**File**: `src/patches/gameDetailPatch.tsx`

Hardcoded allowlist of other plugins' prefixes/type names:
```ts
const PLUGIN_KEY_PREFIXES = ["romm-", "unifideck-", "hltb-", "protondb-"];
const PLUGIN_TYPE_NAMES = ["ProtonMedal", "GameStats", ...];
```

Any unknown plugin shifts the "2nd native child = PlaySection" index. The diagnostic tree dump already searches for `PlaySection` CSS class (lines 130-153) — use that for the actual detection instead of exclusion-based indexing.

**Fix**: Positively identify native PlaySection via CSS class match in tree walk.

---

### 7. Async race in sessionManager `[agent]`
**File**: `src/utils/sessionManager.ts:64-155`

`handleGameStart`/`handleGameStop` are async but `RegisterForAppLifetimeNotifications` doesn't await them. Rapid start+stop interleaves, potentially losing playtime or corrupting session state.

**Fix**: Queue or serialize game lifecycle events.

---

### 8. `retrodeck_config.py` reads from disk on every call `[manual]`
**File**: `lib/retrodeck_config.py`

`get_saves_path()` → `get_retrodeck_path()` → `open()` + `json.load()` on every call. In `sync_all_saves()` with 50 ROMs, that's 50 reads of the same file.

**Fix**: TTL cache (30s) — fresh enough for config changes, fast enough for batch ops.

---

### 9. `es_de_config.py` cache never invalidates on external changes `[manual]`
**File**: `lib/es_de_config.py`

`_es_systems_cache` and `_core_defaults_cache` load once, only reset via `_reset_cache()` after `set_system_core`/`set_game_core`. If user changes core in ES-DE directly, plugin shows stale data until restart.

**Fix**: Invalidate on `get_cached_game_detail()` — called on every game detail page open.

---

### 10. Launcher doesn't exit on "ROM file missing" `[agent]` -- FIXED
**File**: `bin/romm-launcher:73-78`

Prints error but exits 0 and falls through to queue a download request. Should either exit non-zero or explicitly enter the download-request path.

**Fix**: Add `exit 1` after error, or restructure the flow.

---

### 11. Unsafe path concat in migration `[agent]` -- FIXED
**File**: `main.py:125, 142`

Uses `new_home + path[len(old_home):]` instead of `os.path.join(new_home, os.path.relpath(path, old_home))`. Edge case: `old_home="/home/user/retro"` matches `path="/home/user/retrodeck/rom"`.

**Fix**: Use `os.path.relpath()`.

---

### 12. Deep tree dump floods backend at debug level `[manual]`
**File**: `src/patches/gameDetailPatch.tsx`

`deepTreeDump()` runs for every RomM AppId on plugin load, each call goes through the `debugLog` backend callable → `decky.logger.info()`. With 100+ shortcuts and debug logging, this hammers startup.

**Fix**: Gate behind a `tree_dump_enabled` flag, or run for one AppId per session only.

---

## NICE TO HAVE (post-beta)

### 13. Cleared downloads hidden on re-download `[agent]`
**File**: `src/components/DownloadQueue.tsx:27-78`

`cleared` Set in React state persists rom_ids. Re-downloading a previously cleared ROM hides the new progress.

**Fix**: Clear the rom_id from `cleared` when a new `download_progress` event arrives.

---

### 14. Connection state via custom events, not central store `[manual]`
**Files**: `connectionState.ts`, `CustomPlayButton.tsx`, `RomMPlaySection.tsx`, `sessionManager.ts`

Different components can have different connection states due to custom event propagation timing. Not a bug today, but a consistency risk.

**Fix (future)**: EventEmitter or subscriber-pattern store.

---

### 15. Test coverage gaps in es_de_config write paths `[manual]`

37 tests for 674 lines. Read operations well-covered, but write paths (`set_system_override`, `set_game_override`, `_rebuild_game_xml`) and the 4-stage core resolution chain need more edge-case coverage. XML manipulation is where bugs hurt most.

---

### 16. Dead code: `save_steamgriddb_key()` `[agent]`
**File**: `lib/sgdb.py:113-116`

Duplicate of `save_sgdb_api_key()` (line 226). Never called from frontend.

**Fix**: Delete it.

---

### 17. XML parsing duplication in es_de_config.py `[manual]`

Four separate SAX parser implementations with own state management in 674 lines. A shared base parser class could save 100-150 lines. Refactoring candidate when code is stable.

---

### 18. `_romm_upload_multipart` reads entire file into memory `[manual]`
**File**: `lib/romm_client.py:115-122`

Fine for .srm (64KB). Breaks for Phase 7 targets (8MB PS2 memory cards). Already tracked in PLAN.md Phase 7.

---

### 19. Download queue memory growth — EXT-3 `[agent/PLAN.md]`

`_download_queue` grows indefinitely. Documented in PLAN.md but not yet fixed.

---

## NOT BUGS (false positives from agents)

These were flagged but are fine:

| Claim | Why it's fine |
|-------|--------------|
| "Event listener leak in CustomPlayButton" | Handlers are named `const` refs inside `useEffect` with `[]` deps — runs once on mount, cleanup removes same references. Standard React. Verified by manual review + independent agent. |
| "Stale closure in RomMPlaySection save sync check" | Effect has `[info.saveSyncEnabled]` dep. Cleanup sets `cancelled = true`, async callback checks it after each await. `romIdRef` is a ref (always current). No stale closure. |
| "Command injection in romm-launcher via $ROM_ID" | Regex `^romm:([0-9]+)$` at line 14 — digits only. Safe. |
| "SteamClient undefined in DangerZone" | Always injected by Decky loader. Never undefined in plugin context. |
| "Password lost on QAM reopen" | Intentional — masked `"••••"` pattern, by design. |
| "React state-after-unmount warnings" | React 18+ handles gracefully. Console noise, not crashes. |
| "Array mutation in gameDetailPatch" | Standard Decky route patching pattern. Works because tree is reconstructed. |
| "MobX stateTransaction bypass" | Fallback `block()` without MobX guard works — Steam always has MobX loaded. |

---

## Architecture notes

The agent review confirmed:
- **API contract is pristine**: All 87 callables and 7 events match perfectly between frontend and backend (one dead code duplicate `save_steamgriddb_key` — item #16)
- **State persistence is solid**: All writes use atomic `.tmp` + `os.replace()` pattern
- **Build system is clean**: `pnpm build` works, CI is functional, release-please is configured
- **Mixin architecture scales well**: 9 mixins with TYPE_CHECKING Protocol classes for cross-mixin deps
- **586 tests pass** (2 resource warnings, no failures)

Three-layer architecture (Data → Business Logic → Presentation) is clean. The mixin state coupling (all share `self.settings`, `self._state`, `self._save_sync_state`) is the main growth risk, but acceptable at current size. No real DI needed yet — the `conftest.py` fixtures handle test isolation well enough.

---

## Architecture recommendations

### Keep mixins — refactor the pain points instead

The 9-mixin structure works at current scale (5,200 lines backend, 9 mixins, Protocol-typed cross-dependencies). A pattern switch to service classes or dependency injection buys nothing: the coupling lives in the shared state dicts (`self.settings`, `self._state`, `self._save_sync_state`), not in the mixin pattern itself. Swapping patterns moves the coupling, doesn't remove it.

The cost of a full refactor — every test fixture, every `self._state["installed_roms"]` access, the Decky Plugin class as composition root — is 2–3 weeks for zero new features. Phase 7 (multi-emulator) adds 1–2 new mixins at most, well within what the pattern handles.

**When to actually move off mixins**: When two mixins need to call each other's methods and the Protocol classes list more than ~10 methods each. That's the signal that implicit dependencies have outgrown the pattern. Currently the largest Protocol is `_SaveSyncDeps` with ~11 methods — right at the edge, worth monitoring but not acting on yet.

### Step 1: Extract test state factory (now)

The biggest pain point is test boilerplate. All 11 test files have their own `plugin()` fixture constructing nearly identical state dicts (~8 lines of identical setup copy-pasted). Extract a shared factory:

```python
# tests/helpers.py
def make_plugin_state(**overrides):
    base = {
        "shortcut_registry": {},
        "installed_roms": {},
        "last_sync": None,
        "sync_stats": {},
        "downloaded_bios": {},
        "retrodeck_home_path": "",
    }
    base.update(overrides)
    return base

def make_plugin(tmp_path, **state_overrides):
    p = Plugin()
    p.settings = {"romm_url": "", "romm_user": "", "romm_pass": "", "enabled_platforms": {}}
    p._state = make_plugin_state(**state_overrides)
    # ... remaining init
    return p
```

This fixes 80% of the test maintenance burden without touching runtime code. Each fixture drops from ~10 lines to 1–2. Adding a new state field becomes a one-place change instead of 11.

### Step 2: Emulator abstraction layer (Phase 7)

When multi-emulator support lands, introduce `EmulatorBackend` as a standalone class — not a mixin. This is the one place where polymorphism actually earns its keep:

```python
class EmulatorBackend:
    """Resolves paths, launch commands, save locations per emulator."""
    def get_roms_path(self) -> str: ...
    def get_saves_path(self) -> str: ...
    def get_bios_path(self) -> str: ...
    def get_launch_command(self, rom_path: str) -> str: ...

class RetroDeckBackend(EmulatorBackend): ...
class EmuDeckBackend(EmulatorBackend): ...
class StandaloneRetroArchBackend(EmulatorBackend): ...
```

The plugin holds `self._emulator: EmulatorBackend`. Mixins call `self._emulator.get_saves_path()` instead of `retrodeck_config.get_saves_path()`. This decouples emulator-specific code from the mixin structure and makes the mixins emulator-agnostic — which is the actual goal of Phase 7.

### What not to do

- Don't introduce a DI framework. The codebase is too small and Decky's plugin lifecycle doesn't suit it.
- Don't split mixins into separate files with their own state objects. That creates 9 state containers that need synchronizing — strictly worse than the current single-dict approach.
- Don't preemptively refactor for Phase 8. The current architecture carries through Phase 7 comfortably. Reassess after multi-emulator is shipped and real usage patterns emerge.
