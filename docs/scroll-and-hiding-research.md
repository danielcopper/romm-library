# Game Detail Page: Scroll & Native PlaySection Hiding Research

Date: 2026-02-23

## Problem Statement

Two interrelated issues on the game detail page for RomM shortcuts:
1. **Native PlaySection hiding**: Must hide Steam's native PlaySection and show our custom RomMPlaySection
2. **Gamepad scrolling**: Must be able to scroll the entire game detail page using controller d-pad/stick

## Root Cause Discovery

**Gamepad scrolling = focus movement.** Steam's scroll container auto-scrolls to keep the focused element visible. Non-focusable content (plain divs) is invisible to the gamepad — it gets skipped entirely. The scroll container doesn't care about element heights or DOM manipulation — it only cares about `Focusable` components in the React tree.

This means:
- The scroll issue has **nothing to do with defang vs no-defang** — it's about our GameInfoPanel having zero Focusable elements
- Defang (replacing native PlaySection with hidden div in React tree) works fine for hiding
- The `Focusable` + `scrollIntoView` pattern (from SteamGridDB plugin) is the correct approach

## Approaches Investigated

### Approach 1: CDP-Based Hiding (unifideck's approach)
- Connect to Steam's CEF via WebSocket on port 8080, execute JS to hide native PlaySection
- Unifideck does this: finds native Play button by text content, walks up 4 parent levels, sets inline `display:none`
- **Pros**: Proven (unifideck uses it), keeps native in React tree
- **Cons**: ~530 lines new Python code, requires `.cef-enable-remote-debugging` flag, text-based button matching is language-dependent and fragile
- **Could improve**: Use CSS class selector instead of text matching
- **Estimated effort**: ~12-15 hours
- **Files**: Would need `lib/cdp_client.py` (~300 LOC), `lib/cdp_mixin.py` (~120 LOC), changes to `main.py`, `backend.ts`, `RomMPlaySection.tsx`, `gameDetailPatch.tsx`

### Approach 2: HTML `inert` Attribute
- Set `inert` on the native PlaySection via DOM manipulation after render
- `inert` makes entire subtree non-focusable and non-interactive (web standard, Chrome 102+)
- **Pros**: ~10 lines of code, no Python backend, no text matching, language-independent
- **Cons**: Untested in any Decky plugin. Unknown if Steam's gamepad focus engine respects `inert` (it walks the React tree, not just DOM)
- No plugin in the ecosystem uses this

### Approach 3: Wrap Native in Inert Container (React-level)
- Instead of replacing native, wrap it: `createElement('div', { inert: '', style: { height:0, visibility:'hidden' } }, nativePlay)`
- **Pros**: Native stays in React tree (scroll preserved), `inert` blocks focus, React-level operation
- **Cons**: Same uncertainty about Steam respecting `inert`

### Approach 4: Defang + Focusable Sections (current approach improved)
- Keep defang (replace native with hidden div) — proven for hiding
- Add `Focusable` with `noFocusRing` to GameInfoPanel sections so gamepad can step through them
- **Previous attempt failed**: Wrapping the ROOT panel in Focusable broke the layout. The correct pattern is per-SECTION Focusable, not root-level.
- **Cons**: We tried this and it broke layout, but that was root-level wrapping not section-level

### Approach 5: Focusable + `scrollIntoView` on Focus (SteamGridDB pattern) ← BEST
- Wrap each GameInfoPanel section in `Focusable` with `noFocusRing`
- Add `onFocus={(e) => e.target.scrollIntoView({ behavior: 'smooth', block: 'nearest' })}` to each section
- **Pros**: Proven pattern (SteamGridDB uses it for asset grid), explicit scroll control, minimal code
- **Cons**: Makes non-interactive sections focusable (but with noFocusRing, invisible to user)
- **Key insight**: Focusable only on SECTIONS, not the root container. Root Focusable breaks layout.

### Approach 6: Find Scroll Container + Force Reflow
- Locate the actual scroll container DOM element, force a reflow
- **Pros**: Direct fix for height calculation
- **Cons**: Fragile (scroll container class may change), and doesn't address the real issue (focus, not height)

### Approach 7: Replace Native Entirely (splice replace)
- `children.splice(nativePlayIdx, 1, rommPlaySection)` — replace native instead of inserting alongside
- **Pros**: Simplest, native completely gone
- **Cons**: Same scroll issue as defang (which turned out to be unrelated)

## Plugin Ecosystem Survey

| Plugin | Injects into game detail? | Scroll handling | Gamepad handling |
|--------|--------------------------|-----------------|------------------|
| ProtonDB | Yes, badge overlay | ResizeObserver for positioning only | None (not focusable) |
| HLTB | Yes, stats widget | None | DialogButton is naturally focusable |
| GameThemeMusic | Yes, invisible audio player | ScrollPanel on custom pages only | Focusable on custom pages |
| SteamGridDB | No (context menu + custom page) | IntersectionObserver + scrollContainer | **Focusable + scrollIntoView onFocus** |
| Unifideck | Yes, PlaySection + InfoPanel + badge | None (trusts Steam scroll container) | Focusable with flow-children="row" for button rows |

**No plugin has solved the exact problem of making large injected informational content scrollable via gamepad.**

## How Steam's Scroll Container Works (Inferred)

1. Outer scroll container wraps the `InnerContainer`
2. **Gamepad scroll (D-pad up/down) works by moving focus between `Focusable` elements**
3. Scroll container automatically scrolls to keep focused element visible
4. Non-focusable content (plain divs) is scrolled past when focus moves to next Focusable below
5. Without `Focusable`, plain HTML divs are invisible to gamepad navigation

## Key Technical Notes

### Focusable Component
- `flow-children="right"` or `"row"` = horizontal D-pad navigation between children
- `flow-children="column"` = vertical D-pad navigation
- Does NOT trap focus — vertical escape (up/down) works naturally
- `noFocusRing` hides the focus indicator (useful for non-interactive sections)
- `focusWithinClassName` applies a class when a child has focus

### Properties Navigation
- `Navigation.NavigateToAppProperties()` — broken for non-Steam shortcuts (loads forever)
- `SteamClient.Apps.OpenAppSettingsDialog(appId, "")` — works for shortcuts (unifideck uses this with `"general"` section)

### Native PlaySection Hiding
- CSS hiding (`display:none + pointer-events:none`) insufficient — Steam's gamepad focus walks React tree, not DOM
- Defang (replace React element with hidden div) works for removing from focus
- CDP (unifideck) works but heavy and fragile
- `inert` attribute untested in ecosystem

## References

- [Decky Loader Issue #873 (scroll bug)](https://github.com/SteamDeckHomebrew/decky-loader/issues/873)
- [Decky Frontend Lib](https://github.com/SteamDeckHomebrew/decky-frontend-lib)
- [Unifideck](https://github.com/mubaraknumann/unifideck)
- [SteamGridDB Decky](https://github.com/SteamGridDB/decky-steamgriddb)
- [HLTB for Deck](https://github.com/hulkrelax/hltb-for-deck)
- [ProtonDB Decky](https://github.com/OMGDuke/protondb-decky)
- [ThemeDeck](https://github.com/BrenticusMaximus/ThemeDeck)
