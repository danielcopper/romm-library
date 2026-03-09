/**
 * Gamepad scroll helpers for injected game detail content.
 *
 * Steam's gamepad focus engine scrolls to focused elements automatically,
 * but its built-in handler doesn't center them reliably. These helpers
 * use a 50ms delayed scrollTo to override Steam's handler, ensuring
 * focused elements are centered (or scrolled to top) in the viewport.
 *
 * Only DialogButton works as a focusable element in this injection context —
 * Focusable wrappers around non-interactive content don't register with
 * Steam's gamepad engine when injected via routerHook.addPatch.
 */

/** Find the nearest ancestor with overflowY scroll/auto */
function findScrollParent(el: HTMLElement): HTMLElement | null {
  let parent: HTMLElement | null = el.parentElement;
  while (parent) {
    const ov = window.getComputedStyle(parent).overflowY;
    if (ov === "scroll" || ov === "auto") return parent;
    parent = parent.parentElement;
  }
  return null;
}

/**
 * onFocus handler that scrolls the focused element to the center of the
 * scroll container. Use on DialogButton elements for gamepad navigation.
 */
export function scrollFocusedToCenter(e: FocusEvent): void {
  const el = e.currentTarget as HTMLElement;
  setTimeout(() => {
    if (!el) return;
    const scrollParent = findScrollParent(el);
    if (scrollParent) {
      const elRect = el.getBoundingClientRect();
      const spRect = scrollParent.getBoundingClientRect();
      const targetScroll = scrollParent.scrollTop + (elRect.top - spRect.top) - (spRect.height / 2) + (elRect.height / 2);
      scrollParent.scrollTo({ top: targetScroll, behavior: "smooth" });
    }
  }, 50);
}

/**
 * onFocus handler that scrolls to the top of the scroll container.
 * Use on the Play button so navigating back up reveals the banner/hero.
 */
export function scrollToTop(e: FocusEvent): void {
  const el = e.currentTarget as HTMLElement;
  setTimeout(() => {
    if (!el) return;
    const scrollParent = findScrollParent(el);
    if (scrollParent) {
      scrollParent.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, 50);
}
