# Game Detail Page — UI Design & Architecture (Phase 5.6)

## 1. Overview

Phase 5.6 replaces the entire game detail page content area for RomM shortcuts with a custom Unifideck-style layout. Instead of trying to make non-Steam shortcuts look like native Steam games (the MetaDeck approach from Phase 5.5), we build our own complete UI that is purpose-built for ROM games.

This is modeled after [Unifideck](https://github.com/UNIFiDECK/unifideck), which injects two components into Steam's `InnerContainer`:
1. A custom PlaySection (Play/Install button)
2. A custom GameInfoPanel (metadata, actions, status)

Our equivalent:
1. **CustomPlayButton** — Play/Download button with dropdown menu (already working, `src/components/CustomPlayButton.tsx`)
2. **RomMGameInfoPanel** — custom metadata and status panel (`src/components/RomMGameInfoPanel.tsx`) — ✅ IMPLEMENTED

Key files:
- `/home/deck/Repos/decky-romm-sync/src/patches/gameDetailPatch.tsx` — route patch, tree manipulation
- `/home/deck/Repos/decky-romm-sync/src/components/CustomPlayButton.tsx` — play/download button
- `/home/deck/Repos/decky-romm-sync/src/patches/metadataPatches.ts` — store patches for metadata display

## 2. Architecture Decision: Drop BIsModOrShortcut Bypass

### Background

Phase 4B introduced a `BIsModOrShortcut` bypass counter (adapted from MetaDeck) so Steam would render its native metadata sections (description, genres, developer, release date) for our shortcuts. The counter has two modes:
- Default state (counter = 0): `BIsModOrShortcut` returns `false` for our apps, so Steam renders metadata as if they were real games
- During launch: counter temporarily returns `true` so Steam uses the shortcut launch path (exe + launch options)

This lived in `src/patches/metadataPatches.ts` with a complex two-counter system (`bypassCounter` + `bypassBypass`) hooked into `GetGameID`, `GetPrimaryAppID`, `GetPerClientData`, and `BHasRecentlyLaunched`.

### Why we're dropping it

The bypass approach tried to mix two incompatible philosophies:
- **MetaDeck** (augment native UI): Patch `BIsModOrShortcut` so Steam's own rendering engine shows metadata for shortcuts
- **Unifideck** (replace everything custom): Build our own UI, don't fight Steam's rendering

Mixing these caused:
- **Tree structure instability**: Steam's React tree for shortcuts changes depending on `BIsModOrShortcut` return value, making position-based heuristics fragile
- **Counter timing bugs**: The bypass counter causes intermittent first-click launch failures (Phase 6 Bug 9 in PLAN.md) when `bypassBypass` is still > 0 during a launch attempt
- **Debugging pain**: Two interacting counters with hooks on five different methods, shared global state across all shortcuts

### Decision

Drop the `BIsModOrShortcut` bypass entirely for Phase 5.6. Let `BIsModOrShortcut` return `true` (the natural state for non-Steam shortcuts). We own the entire game detail UI.

### What still works without the bypass

- **Launches**: Shortcuts always launch via their exe path. `BIsModOrShortcut` returning `true` is the correct state for launching. The bypass was only needed for rendering.
- **HLTB plugin**: Searches by game name independently. No dependency on `BIsModOrShortcut`.
- **Store patches** (`GetDescriptions`, `GetAssociations`, `BHasStoreCategory`, `GetCanonicalReleaseDate`): These can be kept for our own RomMGameInfoPanel to consume via `appDetailsStore` / `appStore`, but they are no longer needed for native rendering.

### What to keep from metadataPatches.ts

- `applyDirectMutations()` — writes `controller_support`, `metacritic_score`, `m_setStoreCategories` to `SteamAppOverview`. Useful for library grid tooltips and sort/filter.
- `updatePlaytimeDisplay()` / `applyAllPlaytime()` — writes playtime to `SteamAppOverview` MobX state. Still needed.
- `updateMetadataForApp()` — updates the in-memory metadata cache. Our custom panel will read from this.
- Store patches for `GetDescriptions`, `GetAssociations`, etc. — may still be useful for contexts outside the game detail page (library grid hover, search results). Keep but evaluate.

### What to remove

- `BIsModOrShortcut` patch (Patch 5)
- `GetGameID` hooks (Patches 6+7)
- `GetPrimaryAppID` hooks (Patches 8+9)
- `GetPerClientData` hook (Patch 10)
- `BHasRecentlyLaunched` hook
- `bypassCounter` and `bypassBypass` module-level state
- `setBypassBypass()` and `prepareForLaunch()` exports
- The `setBypassBypass(11)` call in `gameDetailPatch.tsx`
- The `prepareForLaunch()` call in `CustomPlayButton.tsx`

## 3. React Tree Structure for Non-Steam Shortcuts

Non-Steam shortcuts have minimal native children in the `InnerContainer`:

1. `HeaderCapsule` — hero banner, logo, header area
2. Plugin injections — `ProtonMedal` (ProtonDB), `GameStats` (HLTB), `AudioLoaderCompat`, etc.
3. `p` element — possibly a native text node or separator

No native PlaySection component exists for non-Steam shortcuts. Steam does not render a PlaySection React component for them — the "Play" button users see is rendered through a different mechanism or at a different tree level.

Diagnostic tree dump logging is built into `gameDetailPatch.tsx` (gated behind the `debug_logging` setting) for future investigation if needed.

## 4. PlaySection Replacement Strategy

### Position-based heuristic

Since there is no reliable CSS class or component type to identify the native PlaySection in the React tree, we use a position-based heuristic:

1. Count children of `InnerContainer`
2. Skip children injected by other plugins (detection below)
3. Replace the 2nd native child (index after `HeaderCapsule`)

This is the same approach Unifideck uses as a fallback. Their primary method (`playSectionClasses.Container` matching) only works on native Steam games.

### Plugin detection

Two detection methods are used together because most plugins don't set React keys:

**By key prefix** (for plugins that set keys):
- `romm-` (our own)
- `unifideck-`
- `hltb-`
- `protondb-`

**By component type name** (for plugins that don't set keys):
- `ProtonMedal` (ProtonDB)
- `GameStats` (HLTB)
- `AudioLoaderCompatStateContextProvider` (AudioLoader)

Both checks are in `gameDetailPatch.tsx` lines 180-191:

```typescript
const PLUGIN_KEY_PREFIXES = ["romm-", "unifideck-", "hltb-", "protondb-"];
const PLUGIN_TYPE_NAMES = ["ProtonMedal", "GameStats", "AudioLoaderCompatStateContextProvider"];
```

### CSS hiding (no longer used for PlaySection)

`styleInjector.ts` still exists and is used by `RomMGameInfoPanel.tsx` and `CustomPlayButton.tsx` for component styling. However, it is no longer used to hide the native PlaySection — splice-replace (removing the element from the React tree entirely) is sufficient and more reliable. CSS hiding cannot prevent Steam's gamepad focus engine from reaching hidden elements since it walks the React tree, not the DOM.

### Splice replacement

The current implementation splices the custom component into the children array, replacing the native element at the detected position:

```typescript
// gameDetailPatch.tsx line 218
children.splice(nativePlayIdx, 1, rommPlaySection);
```

This removes the native component from the React tree entirely, which is the most reliable way to prevent gamepad focus from reaching it.

## 5. Gamepad Navigation

### How Steam's gamepad focus works

Steam's gamepad navigation system traverses the **React component tree**, not the rendered DOM. This has several implications:

- **CSS hiding is insufficient**: `display: none`, `visibility: hidden`, and even `pointer-events: none` cannot fully prevent focus traversal. Steam walks the React tree looking for focusable components regardless of their CSS state.
- **React tree removal is the only reliable fix**: The native component must be removed (spliced out) from the React tree entirely to prevent gamepad focus from landing on it.

### DialogButton for gamepad-focusable content sections

**Key discovery**: `Focusable` wrappers around non-interactive content do NOT register with Steam's gamepad focus engine in the game detail page injection context. However, `DialogButton` from `@decky/ui` (which renders as an actual button element) is natively focusable.

`RomMGameInfoPanel` uses `DialogButton` styled as transparent content sections (no button appearance):

```typescript
const section = (key, title, ...children) =>
  createElement(DialogButton as any, {
    key,
    className: "romm-panel-section",
    style: {
      background: "transparent",
      border: "none",
      padding: "12px 0",
      textAlign: "left",
      width: "100%",
      cursor: "default",
      display: "block",
    },
    noFocusRing: false,
    onFocus: (e) => {
      (e.currentTarget as HTMLElement)?.scrollIntoView?.({
        behavior: "smooth", block: "center"
      });
    },
  },
    title ? createElement("div", { ... }, title) : null,
    ...children,
  );
```

Each section (Game Info, ROM File, Save Sync, BIOS) is individually focusable via gamepad D-pad. When focused, `scrollIntoView({ block: "center" })` ensures the section scrolls into the visible area. `noFocusRing: false` shows the standard Steam focus ring on the selected section.

### Focus styles

Steam applies the `.gpfocus` CSS class to the currently focused element during gamepad navigation. `DialogButton` handles this natively — no custom focus styles needed for the info panel sections.

`CustomPlayButton` in `RomMPlaySection` uses `Focusable` with `appActionButtonClasses.PlayButtonContainer` which integrates with Steam's gamepad focus system for the play/download button area.

### Auto-select play button

When entering the game detail page, the play button is auto-selected (focused) with a 400ms DOM-based delay — confirmed working.

## 6. Compatibility with Other Plugins

### HLTB (How Long to Beat)

- Injects a `GameStats` component into `InnerContainer`
- Searches by game name via HLTB API — completely independent of our plugin
- No dependency on `BIsModOrShortcut` state
- We skip it in our position heuristic via type name detection
- Coexists without issues

### ProtonDB Badges

- Injects a `ProtonMedal` component into `InnerContainer`
- Does NOT set a React key on its injected element
- Detected by type name in our heuristic
- Works independently

### Unifideck

- Same position-based heuristic approach for PlaySection replacement
- Their primary method (`playSectionClasses.Container` CSS class matching) only works on native Steam games
- Both plugins can coexist: ours only activates for RomM games (`isRomM` check via `rommAppIds.has(appId)`), Unifideck handles its own game set
- Test scenarios from PLAN.md:
  - RomM game with Unifideck installed: our patch takes priority, no double-injection
  - Native Steam game with both plugins: Unifideck patches normally, we skip entirely
  - Gamepad navigation works on both RomM and native games with both plugins active
  - Uninstalling one plugin doesn't break the other

### AudioLoader

- Injects `AudioLoaderCompatStateContextProvider` component
- Detected by type name in our heuristic
- No interaction with our functionality

## 7. Layout Design (Phase 5.6)

### Component hierarchy

```
InnerContainer (Steam's native container)
  [0] HeaderCapsule — hero banner, logo (preserved)
  [1] RomMPlaySection (replaces native PlaySection)
  │   └── CustomPlayButton — Play/Download with dropdown
  [2] RomMGameInfoPanel (DialogButton sections for gamepad focus, no action handlers)
      ├── Status Row
      │   ├── Install status (Downloaded / Not Installed)
      │   └── Platform badge (e.g. "Game Boy Advance")
      ├── Game Info
      │   ├── Description / Summary
      │   ├── Developer / Publisher
      │   ├── Genre tags, Release date, Game Modes, Players, Rating
      ├── ROM File
      │   └── Filename
      ├── Save Sync (only when save_sync_enabled)
      │   ├── Last sync check time + status indicator
      │   ├── File count
      │   └── Per-file: filename, "Synced: datetime", "Changed: datetime", path
      └── BIOS (only for platforms that need BIOS)
          ├── Status indicator (green/orange/red) + counts
          └── Per-file: filename + local path
  Actions live in the RomM gear icon menu in RomMPlaySection:
      ├── Refresh Artwork, Refresh Metadata, Sync Save Files, Download BIOS
      └── Uninstall (destructive)
```

### CustomPlayButton states (existing)

The play button (`src/components/CustomPlayButton.tsx`) already handles these states:
- **loading**: Initial mount while checking ROM status
- **not_romm**: Not a RomM shortcut, returns null
- **download**: ROM not installed, blue "Download" button
- **play**: ROM installed, green "Play" button with dropdown (Uninstall)
- **launching**: Brief "Launching..." state with throbber

### Save conflict in play button area

When save sync is enabled and a conflict is detected, the play button should show a blocked state (e.g. crossed circle icon, orange "Resolve Conflict" button). This prevents launching with conflicting save data. Other conflict modes (newest_wins, always_upload, always_download) auto-resolve during the pre-launch check and go straight to Play.

### BIOS section complexity

The BIOS section has edge cases:
- Some platforms don't need BIOS at all (hide the section)
- RomM may list BIOS files that are optional or region-specific — not all "missing" files are actually required (see Phase 6 Bug 7 in PLAN.md)
- Language/region mismatches: user may have JP BIOS but need US BIOS for a specific game

### Conditional visibility

- **Saves & Playtime section**: Only shown when `save_sync_enabled` is `true`. When disabled, section is either hidden or shows "Save Sync disabled — enable in settings" as a non-interactive label.
- **BIOS section**: Only shown for platforms that need BIOS files.
- **Playtime**: Only shown when tracked playtime > 0.

## 8. Open Questions

- **Determine if store patches are still needed**: With a fully custom game detail page, `GetDescriptions`, `GetAssociations`, `BHasStoreCategory`, etc. may be unnecessary. However, they might still be consumed by:
  - Library grid hover tooltips
  - Steam search results
  - Sort/filter in collections
  - Other plugins that read these fields
  Evaluate which contexts still use native rendering and keep patches only for those.

- **Test Unifideck coexistence**: Both plugins use position-based heuristics on `InnerContainer.props.children`. Verify no double-injection or index conflicts when both are active. Test all four scenarios listed in section 6.
