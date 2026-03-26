# Save Sync v2 Polish: Bug Fixes & Quick Wins (#195)

## Overview

Three independent fixes addressing UX issues and a functional bug in the save sync system.

## Item 1: OSK Text Input Fix + None Slot Support

### Problem

Two text inputs use inline `TextField` instead of the modal pattern, causing the on-screen keyboard to open behind the QAM overlay on controller. Additionally, the `None` (legacy/no-slot) mode should be selectable but clearly communicated as limited.

### Text Input Changes

**`SettingsPage.tsx` — Default Slot Name:**
- Replace inline `TextField` + `onBlur` auto-save with a `DialogButton` displaying the current value (or "(no slot)" for null).
- On click: `showModal(<TextInputModal .../>)` with current slot value.
- Empty input on confirm: show warning dialog about legacy single-save limitation, then set `default_slot: null`.
- Non-empty input: `default_slot: trimmed string`.
- Below the input: a "Reset to default" button, only visible when current value differs from `"default"`.

**`RomMGameInfoPanel.tsx` — New Slot creation:**
- Same modal pattern for consistency. Replace inline `TextField` with a button that opens `showModal(<TextInputModal .../>)`.

### Legacy Slot Warnings (active slot is `None`)

Three locations show warnings when the active slot is null:

1. **QAM Settings (`SettingsPage.tsx`)** — Persistent warning banner below the Default Slot field: "Legacy mode (no slot) — saves are limited to one version per game."
2. **Play Button Section (`RomMPlaySection.tsx`)** — Warning icon + short text near save sync status: "Legacy save slot."
3. **Saves Tab (`RomMGameInfoPanel.tsx`)** — Warning banner at top of saves tab: "This game uses legacy mode (no slot). Only one save version per game is supported."

### Backend Changes

**`saves.py` `_sanitize_setting`:**
- Empty string input → `None` (currently rejected, change to accept).
- `None` value → `None` (pass through).
- Non-empty string → trimmed string (unchanged).

**Slot usage in sync** — `saves.py` line 527 already handles `None`: `slot = game_state.get("active_slot", "default") if device_id else None`. Verify this works when `active_slot` is explicitly `None` vs missing key.

## Item 2: Newer Save in Active Slot (#192)

### Problem

When `tracked_save_id` points to an older save (e.g. id=18) but another device uploaded a newer one to the same slot (id=25), the plugin syncs against the old one and shows the new one as a confusing separate entry. No data loss, but confusing UX.

### Detection — `save_sync.py:match_local_to_server_saves()`

In the Priority 1 (tracked_save_id) matching path, after finding the tracked save:
- Look at all server saves in the same slot (regardless of filename — other clients may append timestamps or use different names).
- If any have `updated_at` newer than the tracked save's `updated_at` and were not uploaded by this device: flag as "newer_in_slot".
- Do NOT auto-switch. Do NOT change `tracked_save_id`. Return this info alongside the match.

New field on `MatchedSave`:
```python
newer_save_in_slot: dict | None  # The newer server save, if one exists
```

**Detection timing:** Both pre-launch sync and post-exit sync — wherever `_sync_single_save_file` runs.

### Conflict Surfacing — Service Layer

When `_sync_single_save_file` sees `newer_save_in_slot` is set, it does not proceed with normal sync. Instead it returns a new conflict type `"newer_in_slot"`, distinct from normal local-vs-server conflicts.

### User-Facing Resolution — Frontend

A conflict modal (or dedicated variant) with clear messaging:

**What happened:**
> "Another device uploaded a newer save to slot '{slot}' on {date}. Your plugin is currently tracking an older save (from {date})."

**What this means:**
> "This usually happens when another device uses a different save sync client (like Argosy or the RomM web UI). These tools may create separate save entries instead of updating yours."

**Options:**
1. **"Use the newer save"** — Downloads the newer save, updates `tracked_save_id` to it. Going forward, syncs against this one.
2. **"Keep my current save"** — Stays on the tracked save. The newer one is ignored this time but will be flagged again next sync.
3. **"Keep my current save and stop asking"** — Persists a `dismissed_newer_save_id` per game+slot. If an even newer one appears later, the prompt returns.

**Recommendation (shown after options):**
> "To avoid this in the future, change the default slot on the other device or sync client to a unique name. If that's not possible, change the slot used in this plugin's settings so each client uses its own slot."

### Service State

Per-file state gets:
```python
"dismissed_newer_save_id": int | None  # Suppresses prompt for this specific save ID
```

If a save newer than `dismissed_newer_save_id` appears, the prompt returns.

### Belt-and-Suspenders — `_update_file_sync_state()`

After successful download/upload, always update `tracked_save_id` to the response's save ID. Keeps state fresh for the normal (non-conflict) path.

### Edge Cases

- Tracked save deleted from server: existing Priority 2/3 fallback handles this (falls through to filename match or slot fallback, eventually uploads). No change needed.
- User picks "Use the newer save": download it, update `tracked_save_id`, clear `dismissed_newer_save_id`.

## Item 3: Fix #165 — Lightweight Conflict Key/Type Mismatch

### Problem

Three bugs in `detect_conflict_lightweight`:
1. State writes `local_mtime_at_last_sync` but reader expects `last_sync_local_mtime` → always `None`.
2. Value stored as ISO string but compared as float → would crash if keys matched.
3. `last_sync_local_size` never written → always `None`.

Result: `detect_conflict_lightweight` never detects local changes. Game detail page may incorrectly show "in sync."

### Fix in `saves.py:_update_file_sync_state()`

Add two fields when writing sync state after successful sync:
```python
"last_sync_local_mtime": os.path.getmtime(local_path),  # float (seconds since epoch)
"last_sync_local_size": os.path.getsize(local_path),     # int (bytes)
```

Remove the old `local_mtime_at_last_sync` key — it is never read.

### No change to `save_conflicts.py`

The reader code is correct — expects float mtime and int size. The bug is on the writer side only.

### Backward Compatibility

Old state files won't have the new keys → `file_state.get(...)` returns `None` → lightweight detection returns "indeterminate" → full hash path kicks in. First successful sync after upgrade populates the new keys. No migration needed.

## Files Changed Summary

| Item | Scope | Files |
|------|-------|-------|
| 1. OSK fix + None slot | Frontend + backend | `SettingsPage.tsx`, `RomMGameInfoPanel.tsx`, `RomMPlaySection.tsx`, `saves.py` |
| 2. Newer save in slot | Domain + service + frontend | `save_sync.py`, `saves.py`, `ConflictModal.tsx` (or new variant), `types/index.ts` |
| 3. #165 key mismatch | Backend only | `saves.py` |

## Testing

Each item needs unit tests:

**Item 1:**
- `_sanitize_setting` accepts empty string → `None`, passes through `None`, trims non-empty
- Slot usage with explicit `None` active_slot

**Item 2:**
- `match_local_to_server_saves` detects newer save in same slot from different device
- `match_local_to_server_saves` does not flag saves from own device
- `dismissed_newer_save_id` suppresses prompt for that specific save but not newer ones
- `_update_file_sync_state` updates `tracked_save_id` after sync

**Item 3:**
- `_update_file_sync_state` writes `last_sync_local_mtime` (float) and `last_sync_local_size` (int)
- Old state without new keys → lightweight detection returns indeterminate (graceful fallback)
