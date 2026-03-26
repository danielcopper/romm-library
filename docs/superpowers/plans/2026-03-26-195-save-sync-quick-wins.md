# Save Sync v2 Polish: Bug Fixes & Quick Wins (#195) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three independent save sync issues — OSK text input with None slot support, newer-save-in-slot detection (#192), and lightweight conflict key/type mismatch (#165).

**Architecture:** Three independent items sharing no dependencies. Item 3 is backend-only (smallest). Item 1 is frontend+backend. Item 2 is domain+service+frontend (largest). Each item gets its own commit(s).

**Tech Stack:** Python (backend services/domain), TypeScript/React (frontend components), pytest (testing)

**Spec:** `docs/superpowers/specs/2026-03-26-195-save-sync-quick-wins-design.md`

---

## Task 1: Fix #165 — Lightweight Conflict Key/Type Mismatch (Backend)

**Files:**
- Modify: `py_modules/services/saves.py` — `_update_file_sync_state` method (~line 459)
- Test: `tests/services/test_saves.py`

This is the simplest item. The writer stores `local_mtime_at_last_sync` (ISO string) but the reader in `save_conflicts.py:detect_conflict_lightweight` expects `last_sync_local_mtime` (float). Also `last_sync_local_size` is never written.

- [ ] **Step 1: Write failing tests**

In `tests/services/test_saves.py`, add tests to the appropriate class (or create a new class if none exists for `_update_file_sync_state`):

```python
class TestUpdateFileSyncState:
    """Tests for _update_file_sync_state writing correct keys for lightweight conflict detection."""

    def test_writes_last_sync_local_mtime_as_float(self, tmp_path):
        """Verify last_sync_local_mtime is stored as a float (epoch seconds), not ISO string."""
        svc = _make_service(tmp_path)
        # Create a local save file
        save_file = tmp_path / "saves" / "gba" / "test.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save data")

        server_response = {"id": 1, "updated_at": "2026-03-26T10:00:00+00:00", "file_size_bytes": 9}
        svc._update_file_sync_state("42", "test.srm", server_response, str(save_file), "gba")

        file_state = svc._save_sync_state["saves"]["42"]["files"]["test.srm"]
        mtime = file_state["last_sync_local_mtime"]
        assert isinstance(mtime, float), f"Expected float, got {type(mtime)}"
        assert mtime > 0

    def test_writes_last_sync_local_size_as_int(self, tmp_path):
        """Verify last_sync_local_size is stored as an int (bytes)."""
        svc = _make_service(tmp_path)
        save_file = tmp_path / "saves" / "gba" / "test.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save data")

        server_response = {"id": 1, "updated_at": "2026-03-26T10:00:00+00:00", "file_size_bytes": 9}
        svc._update_file_sync_state("42", "test.srm", server_response, str(save_file), "gba")

        file_state = svc._save_sync_state["saves"]["42"]["files"]["test.srm"]
        size = file_state["last_sync_local_size"]
        assert isinstance(size, int), f"Expected int, got {type(size)}"
        assert size == 9  # len(b"save data")

    def test_does_not_write_old_local_mtime_at_last_sync_key(self, tmp_path):
        """Verify the old mismatched key is no longer written."""
        svc = _make_service(tmp_path)
        save_file = tmp_path / "saves" / "gba" / "test.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save data")

        server_response = {"id": 1, "updated_at": "2026-03-26T10:00:00+00:00", "file_size_bytes": 9}
        svc._update_file_sync_state("42", "test.srm", server_response, str(save_file), "gba")

        file_state = svc._save_sync_state["saves"]["42"]["files"]["test.srm"]
        assert "local_mtime_at_last_sync" not in file_state
```

Note: `_make_service` is a test helper — check `tests/services/test_saves.py` for the existing factory pattern and use the same one. Adapt constructor args as needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/test_saves.py::TestUpdateFileSyncState -v`
Expected: Failures — `last_sync_local_mtime` not in state, `last_sync_local_size` not in state, `local_mtime_at_last_sync` still present.

- [ ] **Step 3: Fix `_update_file_sync_state` in saves.py**

In `py_modules/services/saves.py`, in the `_update_file_sync_state` method (~line 459), replace:

```python
"local_mtime_at_last_sync": local_mtime,
```

with:

```python
"last_sync_local_mtime": os.path.getmtime(local_path) if os.path.isfile(local_path) else None,
"last_sync_local_size": os.path.getsize(local_path) if os.path.isfile(local_path) else None,
```

Also remove the `local_mtime` variable computation above (lines ~453-457 that create the ISO string) since it's no longer used. Make sure the `local_hash` computation above it is kept.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/test_saves.py::TestUpdateFileSyncState -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: All tests pass. If any existing tests relied on `local_mtime_at_last_sync`, update them to use the new keys.

- [ ] **Step 6: Run linting**

Run: `ruff check py_modules/services/saves.py && basedpyright py_modules/services/saves.py`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add py_modules/services/saves.py tests/services/test_saves.py
git commit -m "fix(saves): align lightweight conflict state keys with reader (#165)

Write last_sync_local_mtime (float) and last_sync_local_size (int) in
_update_file_sync_state. Removes old local_mtime_at_last_sync key that
was never read, fixing detect_conflict_lightweight which always returned
indeterminate due to key/type mismatch."
```

---

## Task 2: Backend — Allow `default_slot = None` (Legacy Slot)

**Files:**
- Modify: `py_modules/services/saves.py` — `_sanitize_setting` (~line 1630) and `get_save_sync_settings` (~line 1609)
- Test: `tests/services/test_saves.py`

- [ ] **Step 1: Write failing tests**

```python
class TestSanitizeSettingDefaultSlot:
    """Tests for _sanitize_setting handling of default_slot with None support."""

    def test_empty_string_becomes_none(self, tmp_path):
        """Empty string input should set default_slot to None (legacy mode)."""
        svc = _make_service(tmp_path)
        svc._save_sync_state["settings"]["default_slot"] = "default"
        result = svc.update_save_sync_settings({"default_slot": ""})
        assert result["settings"]["default_slot"] is None

    def test_none_value_passes_through(self, tmp_path):
        """None input should set default_slot to None."""
        svc = _make_service(tmp_path)
        svc._save_sync_state["settings"]["default_slot"] = "default"
        result = svc.update_save_sync_settings({"default_slot": None})
        assert result["settings"]["default_slot"] is None

    def test_whitespace_only_becomes_none(self, tmp_path):
        """Whitespace-only input should set default_slot to None."""
        svc = _make_service(tmp_path)
        result = svc.update_save_sync_settings({"default_slot": "   "})
        assert result["settings"]["default_slot"] is None

    def test_nonempty_string_trimmed(self, tmp_path):
        """Non-empty string is trimmed and stored as-is."""
        svc = _make_service(tmp_path)
        result = svc.update_save_sync_settings({"default_slot": "  desktop  "})
        assert result["settings"]["default_slot"] == "desktop"


class TestSlotUsageWithNoneActiveSlot:
    """Tests that sync uses None slot correctly when active_slot is explicitly None."""

    def test_upload_uses_none_slot_when_active_slot_is_none(self, tmp_path):
        """When active_slot is explicitly None, upload should pass slot=None."""
        svc = _make_service(tmp_path)
        svc._save_sync_state["saves"]["42"] = {
            "active_slot": None,
            "files": {},
            "system": "gba",
        }
        # Verify the slot resolution: game_state.get("active_slot", "default")
        # When active_slot key IS present but set to None, .get() returns None.
        # But the line is: slot = game_state.get("active_slot", "default") if device_id else None
        # This returns None (the value), not "default" (the default).
        game_state = svc._save_sync_state["saves"]["42"]
        slot = game_state.get("active_slot", "default")
        assert slot is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/test_saves.py::TestSanitizeSettingDefaultSlot -v`
Expected: `test_empty_string_becomes_none` fails (currently skipped/rejected).

- [ ] **Step 3: Modify `_sanitize_setting` in saves.py**

Change the `default_slot` branch (~line 1630):

```python
if key == "default_slot":
    if value is None:
        return None, False  # None = legacy mode
    coerced = str(value).strip()
    return (coerced if coerced else None), False  # empty -> None
```

Also update `get_save_sync_settings` (~line 1609): change `settings.setdefault("default_slot", "default")` to keep it as-is — `"default"` is correct for new installs. None is only set by explicit user choice.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/test_saves.py::TestSanitizeSettingDefaultSlot tests/services/test_saves.py::TestSlotUsageWithNoneActiveSlot -v`
Expected: All pass.

- [ ] **Step 5: Check existing default_slot tests still pass**

Run: `python -m pytest tests/services/test_saves.py -k "default_slot" -v`
Expected: All pass. The existing `test_update_default_slot_empty_string_rejected` test will need to be updated — it currently expects empty string to be rejected. Change it to assert `None` instead.

- [ ] **Step 6: Run linting**

Run: `ruff check py_modules/services/saves.py && basedpyright py_modules/services/saves.py`

- [ ] **Step 7: Commit**

```bash
git add py_modules/services/saves.py tests/services/test_saves.py
git commit -m "feat(saves): allow default_slot=None for legacy no-slot mode

Empty string or None input now sets default_slot to None instead of
being rejected. Legacy mode limits saves to one version per game."
```

---

## Task 3: Frontend — OSK Modal for Default Slot + Legacy Warnings

**Files:**
- Modify: `src/components/SettingsPage.tsx` — Replace inline TextField with modal pattern, add legacy warning + reset button
- Modify: `src/components/RomMGameInfoPanel.tsx` — Replace inline new-slot input with modal, add legacy warning in saves tab
- Modify: `src/components/RomMPlaySection.tsx` — Add legacy slot warning near save sync status

- [ ] **Step 1: Modify SettingsPage.tsx — Default Slot input**

Replace the inline `TextField` for Default Save Slot (~lines 559-578) with a `DialogButton` + modal pattern matching the URL/username/password fields:

```tsx
<PanelSectionRow>
  <Field
    label="Default Save Slot"
    description={saveSyncSettings.default_slot ?? "(no slot)"}
  >
    <DialogButton onClick={() => showModal(
      <TextInputModal
        label="Default Save Slot"
        value={saveSyncSettings.default_slot ?? ""}
        onSubmit={(value) => {
          const trimmed = value.trim();
          if (!trimmed) {
            // Empty = None/legacy mode — confirm with user
            showModal(
              <ConfirmModal
                strTitle="Use Legacy Mode?"
                strDescription="Legacy mode (no slot) limits saves to one version per game. Are you sure?"
                onOK={() => {
                  setSaveSyncSettings((prev) => prev ? { ...prev, default_slot: null as any } : prev);
                  handleSaveSyncSettingChange({ default_slot: "" });
                }}
              />
            );
          } else {
            setSaveSyncSettings((prev) => prev ? { ...prev, default_slot: trimmed } : prev);
            handleSaveSyncSettingChange({ default_slot: trimmed });
          }
        }}
      />
    )}>
      Edit
    </DialogButton>
  </Field>
</PanelSectionRow>
```

Add the "Reset to default" button below, only visible when value differs from `"default"`:

```tsx
{saveSyncSettings.default_slot !== "default" && (
  <PanelSectionRow>
    <ButtonItem
      layout="below"
      onClick={() => {
        setSaveSyncSettings((prev) => prev ? { ...prev, default_slot: "default" } : prev);
        handleSaveSyncSettingChange({ default_slot: "default" });
      }}
    >
      Reset to default
    </ButtonItem>
  </PanelSectionRow>
)}
```

Add legacy warning banner when slot is null:

```tsx
{saveSyncSettings.default_slot == null && (
  <PanelSectionRow>
    <Field
      label={<span style={{ color: "#ff8800" }}>Legacy mode (no slot)</span>}
      description="Saves are limited to one version per game."
    />
  </PanelSectionRow>
)}
```

Note: The `TextInputModal` needs a small update — currently `field` is typed as `"url" | "username" | "password"`. Either broaden it or make `field` optional (it already is — just don't pass it for the slot input, and skip the `pendingEdits` assignment in `onOK`).

- [ ] **Step 2: Modify RomMGameInfoPanel.tsx — New Slot modal**

Replace the inline `<input>` element (~lines 951-985) with a `DialogButton` that opens `showModal`. The "+ New Slot" button stays, but instead of toggling `showNewSlotInput` state, it directly opens a modal:

```tsx
createElement(DialogButton as any, {
  key: "new-slot-btn",
  style: { padding: "4px 8px", minWidth: "auto", fontSize: "12px", marginTop: "8px" },
  onClick: () => {
    showModal(
      <TextInputModal
        label="New Slot Name"
        value=""
        onSubmit={async (name: string) => {
          const trimmed = name.trim();
          if (!trimmed || !state.romId) return;
          const result = await setGameSlot(state.romId, trimmed);
          if (result.success) {
            setState((prev) => ({
              ...prev,
              activeSlot: trimmed,
              availableSlots: prev.availableSlots.some((s) => s.slot === trimmed)
                ? prev.availableSlots
                : [...prev.availableSlots, { slot: trimmed, source: "local" as const, count: 0, latest_updated_at: null }],
            }));
            globalThis.dispatchEvent(new CustomEvent("romm_data_changed", { detail: { type: "save_sync", rom_id: state.romId } }));
          }
        }}
      />
    );
  },
  noFocusRing: false,
}, "+ New Slot"),
```

Remove the `showNewSlotInput` / `newSlotInput` state fields and the conditional rendering block for the inline input.

Import `TextInputModal` from `./SettingsPage` or extract it to a shared location. If it's not exported, export it.

Add legacy warning at top of saves tab when game's active_slot is null:

```tsx
if (state.activeSlot == null) {
  leftColumnChildren.unshift(
    createElement("div", {
      key: "legacy-warning",
      style: { padding: "8px", background: "rgba(255, 136, 0, 0.15)", borderRadius: "4px", border: "1px solid rgba(255, 136, 0, 0.3)", marginBottom: "8px", fontSize: "12px", color: "#ff8800" },
    }, "This game uses legacy mode (no slot). Only one save version per game is supported."),
  );
}
```

- [ ] **Step 3: Modify RomMPlaySection.tsx — Legacy slot warning**

Find where save sync status is displayed and add a warning when the game's active slot is null. This will be a small inline warning icon + text:

```tsx
{activeSlot == null && saveSyncEnabled && (
  <div style={{ fontSize: "11px", color: "#ff8800", marginTop: "4px" }}>
    ⚠ Legacy save slot
  </div>
)}
```

The exact location depends on how `RomMPlaySection` accesses save state. Check whether it already has `activeSlot` in its state or needs to read it from save sync state.

- [ ] **Step 4: Update SaveSyncSettings type**

In `src/types/index.ts`, update the `default_slot` field to allow null:

```typescript
default_slot: string | null;
```

- [ ] **Step 5: Build and verify**

Run: `pnpm build`
Expected: No TypeScript errors, no warnings. `dist/index.js` generated.

- [ ] **Step 6: Commit**

```bash
git add src/components/SettingsPage.tsx src/components/RomMGameInfoPanel.tsx src/components/RomMPlaySection.tsx src/types/index.ts
git commit -m "feat(saves): OSK modal for slot inputs + legacy slot warnings

Replace inline TextFields with showModal pattern for Default Slot (QAM)
and New Slot (game detail) inputs. Add legacy mode warnings in QAM
settings, play section, and saves tab when slot is null. Add Reset to
default button."
```

---

## Task 4: Domain — Detect Newer Save in Slot (#192)

**Files:**
- Modify: `py_modules/domain/save_sync.py` — Add `newer_save_in_slot` field to `MatchedSave`, add detection in `_match_single_local_file`
- Test: `tests/domain/test_save_matching.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/domain/test_save_matching.py`:

```python
class TestNewerSaveInSlotDetection:
    """Tests for detecting newer saves uploaded by other devices in the same slot."""

    def test_detects_newer_save_in_same_slot(self):
        """When tracked save exists but a newer save is in the same slot, flag it."""
        local_files = [{"filename": "game.srm", "path": "/saves/gba/game.srm"}]
        server_saves = [
            {"id": 18, "file_name": "game.srm", "slot": "default", "updated_at": "2026-03-20T10:00:00+00:00", "file_size_bytes": 100},
            {"id": 25, "file_name": "game_20260325.srm", "slot": "default", "updated_at": "2026-03-25T10:00:00+00:00", "file_size_bytes": 120},
        ]
        files_state = {"game.srm": {"tracked_save_id": 18}}

        result = match_local_to_server_saves(local_files, server_saves, files_state, "default")
        matched = result.matched[0]

        assert matched.match_method == "tracked_id"
        assert matched.server_save["id"] == 18  # Still tracking the old one
        assert matched.newer_save_in_slot is not None
        assert matched.newer_save_in_slot["id"] == 25

    def test_no_flag_when_tracked_is_newest(self):
        """When tracked save is already the newest, no newer_save_in_slot."""
        local_files = [{"filename": "game.srm", "path": "/saves/gba/game.srm"}]
        server_saves = [
            {"id": 18, "file_name": "game.srm", "slot": "default", "updated_at": "2026-03-25T10:00:00+00:00", "file_size_bytes": 100},
        ]
        files_state = {"game.srm": {"tracked_save_id": 18}}

        result = match_local_to_server_saves(local_files, server_saves, files_state, "default")
        assert result.matched[0].newer_save_in_slot is None

    def test_ignores_saves_in_different_slot(self):
        """Newer saves in a different slot should not trigger detection."""
        local_files = [{"filename": "game.srm", "path": "/saves/gba/game.srm"}]
        server_saves = [
            {"id": 18, "file_name": "game.srm", "slot": "default", "updated_at": "2026-03-20T10:00:00+00:00", "file_size_bytes": 100},
            {"id": 30, "file_name": "game.srm", "slot": "other-device", "updated_at": "2026-03-25T10:00:00+00:00", "file_size_bytes": 120},
        ]
        files_state = {"game.srm": {"tracked_save_id": 18}}

        result = match_local_to_server_saves(local_files, server_saves, files_state, "default")
        assert result.matched[0].newer_save_in_slot is None

    def test_no_flag_for_non_tracked_id_match(self):
        """newer_save_in_slot only applies to tracked_id matches (Priority 1)."""
        local_files = [{"filename": "game.srm", "path": "/saves/gba/game.srm"}]
        server_saves = [
            {"id": 18, "file_name": "game.srm", "slot": "default", "updated_at": "2026-03-20T10:00:00+00:00", "file_size_bytes": 100},
            {"id": 25, "file_name": "game_newer.srm", "slot": "default", "updated_at": "2026-03-25T10:00:00+00:00", "file_size_bytes": 120},
        ]
        files_state = {}  # No tracked_save_id — will match by filename (Priority 2)

        result = match_local_to_server_saves(local_files, server_saves, files_state, "default")
        assert result.matched[0].match_method == "filename"
        assert result.matched[0].newer_save_in_slot is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/domain/test_save_matching.py::TestNewerSaveInSlotDetection -v`
Expected: Failures — `MatchedSave` has no `newer_save_in_slot` attribute.

- [ ] **Step 3: Add `newer_save_in_slot` to MatchedSave dataclass**

In `py_modules/domain/save_sync.py`, update the `MatchedSave` dataclass:

```python
@dataclass
class MatchedSave:
    """A local file matched to a server save."""

    local_file: dict | None
    server_save: dict | None
    filename: str
    match_method: str
    newer_save_in_slot: dict | None = None  # Set when a newer save exists in the same slot from another device
```

- [ ] **Step 4: Add detection logic in `_match_single_local_file`**

After the Priority 1 match (line ~108), add the newer-in-slot check:

```python
    # Priority 1: tracked_save_id
    tracked_id = file_state.get("tracked_save_id")
    newer_in_slot: dict | None = None
    if tracked_id and tracked_id in server_by_id:
        server = server_by_id[tracked_id]
        method = "tracked_id"
        # Check for newer saves in the same slot from other devices
        tracked_slot = server.get("slot")
        tracked_updated = server.get("updated_at", "")
        candidates = [
            ss for ss in server_saves
            if ss.get("slot") == tracked_slot
            and ss.get("id") != tracked_id
            and ss.get("updated_at", "") > tracked_updated
        ]
        if candidates:
            newer_in_slot = max(candidates, key=lambda s: s.get("updated_at", ""))
```

Then pass it into the return:

```python
    return MatchedSave(
        local_file=lf,
        server_save=server,
        filename=fn,
        match_method=method,
        newer_save_in_slot=newer_in_slot,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/domain/test_save_matching.py::TestNewerSaveInSlotDetection -v`
Expected: All 4 tests PASS.

- [ ] **Step 6: Run full domain tests + linting**

Run: `python -m pytest tests/domain/ -q && ruff check py_modules/domain/save_sync.py && basedpyright py_modules/domain/save_sync.py`

- [ ] **Step 7: Commit**

```bash
git add py_modules/domain/save_sync.py tests/domain/test_save_matching.py
git commit -m "feat(saves): detect newer save in slot during matching (#192)

Add newer_save_in_slot field to MatchedSave. When a tracked_id match
finds a newer save in the same slot (from another device/client),
it flags it without auto-switching tracked_save_id."
```

---

## Task 5: Service — Handle `newer_in_slot` Conflict + Belt-and-Suspenders

**Files:**
- Modify: `py_modules/services/saves.py` — `_sync_single_save_file`, `_process_single_file_sync`, `_update_file_sync_state`, `resolve_newer_in_slot`
- Modify: `py_modules/models/saves.py` — Add `NewerInSlotConflict` dataclass (or extend `SaveConflict`)
- Test: `tests/services/test_saves.py`

- [ ] **Step 1: Write failing tests**

```python
class TestNewerInSlotConflict:
    """Tests for newer_in_slot conflict surfacing in service layer."""

    @pytest.mark.asyncio
    async def test_newer_in_slot_returns_ask_with_newer_info(self, tmp_path):
        """When match has newer_save_in_slot, sync should return newer_in_slot conflict."""
        svc = _make_service(tmp_path)
        # Set up state with tracked save
        svc._save_sync_state["saves"]["42"] = {
            "files": {"game.srm": {"tracked_save_id": 18, "last_sync_hash": "abc123"}},
            "system": "gba",
            "active_slot": "default",
        }
        # The service's _sync_rom_saves calls match_local_to_server_saves which
        # will detect newer_in_slot. We need to verify the conflict is surfaced.
        # This test may need to be structured as an integration test through
        # _process_single_file_sync or _sync_single_save_file.
        # Adapt to the existing test patterns in test_saves.py.
        pass  # Implementation depends on existing test infrastructure

    def test_dismissed_newer_save_id_suppresses_conflict(self, tmp_path):
        """When dismissed_newer_save_id matches the newer save, no conflict surfaced."""
        svc = _make_service(tmp_path)
        svc._save_sync_state["saves"]["42"] = {
            "files": {"game.srm": {
                "tracked_save_id": 18,
                "last_sync_hash": "abc123",
                "dismissed_newer_save_id": 25,
            }},
            "system": "gba",
            "active_slot": "default",
        }
        # Newer save id=25 should be suppressed
        # Newer save id=30 (even newer) should NOT be suppressed
        pass  # Adapt to existing test patterns

    def test_update_file_sync_state_updates_tracked_save_id(self, tmp_path):
        """After sync, tracked_save_id should be updated to the server response's id."""
        svc = _make_service(tmp_path)
        save_file = tmp_path / "saves" / "gba" / "test.srm"
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_bytes(b"save data")

        # First sync with save_id=18
        svc._update_file_sync_state("42", "test.srm", {"id": 18, "updated_at": "2026-03-20T10:00:00+00:00", "file_size_bytes": 9}, str(save_file), "gba")
        assert svc._save_sync_state["saves"]["42"]["files"]["test.srm"]["tracked_save_id"] == 18

        # Second sync with save_id=25 (belt-and-suspenders: tracked_save_id gets updated)
        svc._update_file_sync_state("42", "test.srm", {"id": 25, "updated_at": "2026-03-25T10:00:00+00:00", "file_size_bytes": 9}, str(save_file), "gba")
        assert svc._save_sync_state["saves"]["42"]["files"]["test.srm"]["tracked_save_id"] == 25
```

Note: The first two tests are sketches — adapt to the actual test infrastructure in `test_saves.py`. Look at how existing sync tests set up FakeSaveApi and call the service methods.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/services/test_saves.py::TestNewerInSlotConflict -v`

- [ ] **Step 3: Implement service-layer changes**

**In `_process_single_file_sync` (~line 653):** Before calling `_sync_single_save_file`, check if the `MatchedSave` has `newer_save_in_slot`. This requires passing the `MatchedSave` object instead of just `local`/`server` separately. Modify the loop in `_sync_rom_saves` (~line 762):

```python
for m in match_result.matched:
    # Check for newer-in-slot before normal sync
    if m.newer_save_in_slot:
        file_state = files_state.get(m.filename, {})
        dismissed_id = file_state.get("dismissed_newer_save_id")
        newer_id = m.newer_save_in_slot.get("id")
        if dismissed_id is None or (newer_id is not None and newer_id > dismissed_id):
            # Surface as a special conflict
            conflicts.append(_build_newer_in_slot_conflict(
                rom_id, m.filename, m.server_save, m.newer_save_in_slot,
                save_state.get("active_slot"),
            ))
            continue  # Skip normal sync for this file
    # ... existing sync logic
```

Add a helper to build the newer-in-slot conflict dict:

```python
def _build_newer_in_slot_conflict(
    rom_id: int,
    filename: str,
    tracked_save: dict | None,
    newer_save: dict,
    slot: str | None,
) -> dict:
    """Build a newer-in-slot conflict descriptor for the frontend."""
    return {
        "type": "newer_in_slot",
        "rom_id": rom_id,
        "filename": filename,
        "tracked_save_id": tracked_save.get("id") if tracked_save else None,
        "tracked_updated_at": tracked_save.get("updated_at") if tracked_save else None,
        "newer_save_id": newer_save.get("id"),
        "newer_updated_at": newer_save.get("updated_at"),
        "slot": slot,
    }
```

**Add resolution callable in `main.py`:** Add a new callable `resolve_newer_in_slot(rom_id, filename, resolution, newer_save_id)` where resolution is `"use_newer"`, `"keep_current"`, or `"dismiss"`.

- `"use_newer"`: Download the newer save, update `tracked_save_id` to `newer_save_id`, clear `dismissed_newer_save_id`.
- `"keep_current"`: No action this time.
- `"dismiss"`: Set `dismissed_newer_save_id = newer_save_id` in file state.

**Belt-and-suspenders in `_update_file_sync_state`:** The `tracked_save_id` line already exists (~line 466): `"tracked_save_id": server_response.get("id")`. This already updates on every sync. Verify it works by checking the test from Step 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/services/test_saves.py::TestNewerInSlotConflict -v`

- [ ] **Step 5: Run full test suite + linting**

Run: `python -m pytest tests/ -q && ruff check py_modules/ main.py && basedpyright py_modules/ main.py`

- [ ] **Step 6: Commit**

```bash
git add py_modules/services/saves.py py_modules/models/saves.py main.py tests/services/test_saves.py
git commit -m "feat(saves): surface newer-in-slot conflict + resolution (#192)

When a tracked save has a newer version in the same slot from another
device, surface a special conflict type. User can choose to use the
newer save, keep current, or dismiss (per-save suppression).
tracked_save_id is updated after every successful sync operation."
```

---

## Task 6: Frontend — Newer-in-Slot Conflict Modal

**Files:**
- Create: `src/components/NewerInSlotModal.tsx`
- Modify: `src/components/CustomPlayButton.tsx` — Handle `newer_in_slot` conflict type
- Modify: `src/api/backend.ts` — Add `resolveNewerInSlot` callable
- Modify: `src/types/index.ts` — Add `NewerInSlotConflict` type

- [ ] **Step 1: Add types**

In `src/types/index.ts`:

```typescript
export interface NewerInSlotConflict {
  type: "newer_in_slot";
  rom_id: number;
  filename: string;
  tracked_save_id: number | null;
  tracked_updated_at: string | null;
  newer_save_id: number;
  newer_updated_at: string;
  slot: string | null;
}
```

- [ ] **Step 2: Add callable**

In `src/api/backend.ts`:

```typescript
export const resolveNewerInSlot = callable<
  [number, string, "use_newer" | "keep_current" | "dismiss", number],
  { success: boolean; message?: string }
>("resolve_newer_in_slot");
```

- [ ] **Step 3: Create NewerInSlotModal.tsx**

```tsx
import { FC } from "react";
import { ModalRoot, DialogButton } from "@decky/ui";
import { resolveNewerInSlot, logError } from "../api/backend";
import type { NewerInSlotConflict } from "../types";
import { showModal } from "@decky/ui";

export type NewerInSlotResolution = "use_newer" | "keep_current" | "dismiss" | "cancel";

interface NewerInSlotModalProps {
  conflict: NewerInSlotConflict;
  closeModal?: () => void;
  onDone: (resolution: NewerInSlotResolution) => void;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "unknown";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

const NewerInSlotModalContent: FC<NewerInSlotModalProps> = ({ conflict, closeModal, onDone }) => {
  const handleChoice = async (resolution: NewerInSlotResolution) => {
    if (resolution !== "cancel") {
      try {
        await resolveNewerInSlot(
          conflict.rom_id,
          conflict.filename,
          resolution === "cancel" ? "keep_current" : resolution,
          conflict.newer_save_id,
        );
      } catch (e) {
        logError(`Failed to resolve newer-in-slot: ${e}`);
        return;
      }
    }
    closeModal?.();
    onDone(resolution);
  };

  const slotDisplay = conflict.slot ?? "(no slot)";

  return (
    <ModalRoot closeModal={() => { closeModal?.(); onDone("cancel"); }}>
      <div style={{ padding: "16px", minWidth: "320px" }}>
        <div style={{ fontSize: "16px", fontWeight: "bold", marginBottom: "4px", color: "#fff" }}>
          Newer Save Detected
        </div>

        <div style={{ fontSize: "13px", color: "rgba(255, 255, 255, 0.7)", marginBottom: "12px" }}>
          Another device uploaded a newer save to slot "{slotDisplay}" on {formatTimestamp(conflict.newer_updated_at)}.
          Your plugin is currently tracking an older save (from {formatTimestamp(conflict.tracked_updated_at)}).
        </div>

        <div style={{ fontSize: "12px", color: "rgba(255, 255, 255, 0.5)", marginBottom: "16px", fontStyle: "italic" }}>
          This usually happens when another device uses a different save sync client (like Argosy or the RomM web UI).
          These tools may create separate save entries instead of updating yours.
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <DialogButton onClick={() => handleChoice("use_newer")}>
            Use the newer save
          </DialogButton>
          <DialogButton onClick={() => handleChoice("keep_current")}>
            Keep my current save
          </DialogButton>
          <DialogButton onClick={() => handleChoice("dismiss")} style={{ opacity: 0.7 }}>
            Keep my current save and stop asking
          </DialogButton>
          <DialogButton onClick={() => handleChoice("cancel")} style={{ opacity: 0.5 }}>
            Cancel
          </DialogButton>
        </div>

        <div style={{ fontSize: "11px", color: "rgba(255, 255, 255, 0.4)", marginTop: "12px" }}>
          To avoid this in the future, change the default slot on the other device or sync client to a unique name.
          If that's not possible, change the slot used in this plugin's settings so each client uses its own slot.
        </div>
      </div>
    </ModalRoot>
  );
};

export function showNewerInSlotModal(
  conflict: NewerInSlotConflict,
): Promise<NewerInSlotResolution> {
  return new Promise<NewerInSlotResolution>((resolve) => {
    showModal(
      <NewerInSlotModalContent conflict={conflict} onDone={resolve} />,
    );
  });
}
```

- [ ] **Step 4: Wire into CustomPlayButton.tsx**

In `CustomPlayButton.tsx`, where conflicts are handled after `preLaunchSync` (~line 300), check if the response includes `newer_in_slot` conflicts and show the dedicated modal:

```tsx
// After getting sync result
const newerInSlot = result.conflicts?.filter((c: any) => c.type === "newer_in_slot") ?? [];
const regularConflicts = result.conflicts?.filter((c: any) => c.type !== "newer_in_slot") ?? [];

// Handle newer-in-slot conflicts first
for (const nis of newerInSlot) {
  const resolution = await showNewerInSlotModal(nis);
  if (resolution === "cancel") return; // Abort launch
}

// Then handle regular conflicts as before
if (regularConflicts.length > 0) {
  const resolution = await showConflictResolutionModal(regularConflicts);
  // ... existing logic
}
```

The same pattern applies in the post-exit sync path in `sessionManager` if applicable.

- [ ] **Step 5: Build and verify**

Run: `pnpm build`
Expected: No errors, no warnings.

- [ ] **Step 6: Commit**

```bash
git add src/components/NewerInSlotModal.tsx src/components/CustomPlayButton.tsx src/api/backend.ts src/types/index.ts
git commit -m "feat(saves): newer-in-slot conflict modal with resolution options (#192)

Show dedicated modal when another device uploaded a newer save to the
same slot. Three options: use newer, keep current, or dismiss.
Includes recommendation text about using separate slots per device."
```

---

## Task 7: Final Verification

- [ ] **Step 1: Run full backend test suite with coverage**

Run: `python -m pytest tests/ -q --cov=py_modules --cov=main --cov-report=term --cov-branch`
Expected: All tests pass, no regressions.

- [ ] **Step 2: Run full linting suite**

Run: `ruff check py_modules/ main.py tests/ && basedpyright py_modules/ main.py tests/`
Expected: No errors.

- [ ] **Step 3: Build frontend**

Run: `pnpm build`
Expected: No errors, no warnings.

- [ ] **Step 4: Verify all three items addressed**

- Item 1 (OSK fix): SettingsPage uses modal for default slot, RomMGameInfoPanel uses modal for new slot, legacy warnings in 3 locations, reset button present.
- Item 2 (#192): `MatchedSave.newer_save_in_slot` detected in domain, surfaced in service, displayed in `NewerInSlotModal`, resolution callable working.
- Item 3 (#165): `_update_file_sync_state` writes `last_sync_local_mtime` (float) and `last_sync_local_size` (int), old key removed.
