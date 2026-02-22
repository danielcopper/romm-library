import { createElement } from "react";
import { routerHook } from "@decky/api";
import {
  afterPatch,
  findInReactTree,
  appDetailsClasses,
  createReactTreePatcher,
  playSectionClasses,
  basicAppDetailsSectionStylerClasses,
} from "@decky/ui";
import { RomMPlaySection } from "../components/RomMPlaySection";
import { debugLog } from "../api/backend";
import type { RoutePatch } from "@decky/api";

// Cached set of RomM app IDs — updated by registerRomMAppId / unregisterRomMAppId
const rommAppIds = new Set<number>();

// Tracks which appIds have already had their tree dumped (once per page load)
const dumpedAppIds = new Set<number>();

/**
 * Recursively walk a React element tree and log each node.
 * Useful for diagnosing tree structure changes after Steam updates.
 * Runs once per appId to avoid log spam on re-renders.
 */
function deepTreeDump(node: any, depth: number, index: number, prefix: string): void {
  if (depth > 5) return;
  if (node == null || typeof node !== "object") return;

  const indent = "  ".repeat(depth);
  const typeName =
    node?.type?.name ||
    node?.type?.displayName ||
    (typeof node?.type === "string" ? node.type : typeof node?.type === "function" ? "(anonymous fn)" : String(node?.type ?? "null"));
  const key = node?.key ?? "null";
  const className = (node?.props?.className || "").substring(0, 60) || "(none)";
  const childrenRaw = node?.props?.children;
  const childCount = Array.isArray(childrenRaw)
    ? childrenRaw.length
    : childrenRaw != null
    ? 1
    : 0;

  debugLog(`${prefix}${indent}[${depth}:${index}] type=${typeName} key=${key} cls=${className} children=${childCount}`);

  // Recurse into children
  if (Array.isArray(childrenRaw)) {
    for (let i = 0; i < childrenRaw.length; i++) {
      deepTreeDump(childrenRaw[i], depth + 1, i, prefix);
    }
  } else if (childrenRaw != null && typeof childrenRaw === "object") {
    deepTreeDump(childrenRaw, depth + 1, 0, prefix);
  }
}

export function registerRomMAppId(appId: number) {
  rommAppIds.add(appId);
}

export function unregisterRomMAppId(appId: number) {
  rommAppIds.delete(appId);
}

export function isRomMAppId(appId: number): boolean {
  return rommAppIds.has(appId);
}

let gamePatch: RoutePatch | null = null;

export function registerGameDetailPatch() {
  gamePatch = routerHook.addPatch(
    "/library/app/:appid",
    (tree: any) => {
      const routeProps = findInReactTree(tree, (x: any) => x?.renderFunc);
      if (routeProps) {
        const patchHandler = createReactTreePatcher(
          [
            // Navigate to the node whose children carry the overview prop
            (node: any) =>
              findInReactTree(
                node,
                (x: any) => x?.props?.children?.props?.overview,
              )?.props?.children,
          ],
          (_args: unknown[], ret?: any) => {
            // Find the InnerContainer by its CSS class
            const container = findInReactTree(
              ret,
              (x: any) =>
                Array.isArray(x?.props?.children) &&
                x?.props?.className?.includes(appDetailsClasses.InnerContainer),
            );

            if (typeof container !== "object" || !container) {
              return ret;
            }

            // Extract appId from the overview object higher up in the tree
            const overviewNode = findInReactTree(
              ret,
              (x: any) => x?.props?.overview?.appid,
            );
            const appId: number | undefined =
              overviewNode?.props?.overview?.appid;

            if (!appId) {
              return ret;
            }

            // Only apply RomM modifications for RomM shortcuts
            const isRomM = rommAppIds.has(appId);
            debugLog(`gameDetailPatch: appId=${appId} isRomM=${isRomM} setSize=${rommAppIds.size}`);

            // Diagnostic tree dump — runs once per appId per plugin load.
            // Logs the full InnerContainer structure for debugging tree changes.
            if (isRomM && !dumpedAppIds.has(appId)) {
              dumpedAppIds.add(appId);
              debugLog(`===== DEEP TREE DUMP for appId=${appId} =====`);
              debugLog(`InnerContainer className: ${container.props.className}`);

              const children = container.props.children;
              debugLog(`InnerContainer direct children count: ${children.length}`);
              for (let i = 0; i < children.length; i++) {
                deepTreeDump(children[i], 0, i, "TREE: ");
              }

              // Search for playSectionClasses.Container deep in tree
              const psContainerClass = playSectionClasses?.Container;
              debugLog(`playSectionClasses.Container = "${psContainerClass || "UNDEFINED"}"`);
              if (psContainerClass) {
                const psFound = findInReactTree(
                  container,
                  (x: any) => x?.props?.className?.includes?.(psContainerClass),
                );
                debugLog(`findInReactTree(playSectionClasses.Container): ${psFound ? "FOUND" : "NOT FOUND"}`);
                if (psFound) {
                  debugLog(`  -> type=${psFound?.type?.name || psFound?.type?.displayName || typeof psFound?.type} cls=${(psFound?.props?.className || "").substring(0, 80)}`);
                }
              }

              // Search for basicAppDetailsSectionStylerClasses.PlaySection deep in tree
              const bpsClass = basicAppDetailsSectionStylerClasses?.PlaySection;
              debugLog(`basicAppDetailsSectionStylerClasses.PlaySection = "${bpsClass || "UNDEFINED"}"`);
              if (bpsClass) {
                const bpsFound = findInReactTree(
                  container,
                  (x: any) => x?.props?.className?.includes?.(bpsClass),
                );
                debugLog(`findInReactTree(basicAppDetailsSectionStylerClasses.PlaySection): ${bpsFound ? "FOUND" : "NOT FOUND"}`);
                if (bpsFound) {
                  debugLog(`  -> type=${bpsFound?.type?.name || bpsFound?.type?.displayName || typeof bpsFound?.type} cls=${(bpsFound?.props?.className || "").substring(0, 80)}`);
                }
              }

              debugLog(`===== END DEEP TREE DUMP =====`);
            }

            // For RomM games: inject CustomPlayButton into InnerContainer,
            // REPLACING the native PlaySection so gamepad focus can't reach it
            if (isRomM) {
              const children = container.props.children;

              // Deduplication: don't insert if already present
              const alreadyHasPlayBtn = children.some(
                (c: any) => c?.key === "romm-play-section",
              );
              if (!alreadyHasPlayBtn) {
                // Identify the native PlaySection by position. Steam's
                // InnerContainer native order is [HeaderCapsule, PlaySection, ...].
                // Skip children injected by other plugins. Detection uses both
                // key prefixes AND component type names, since most plugins
                // (ProtonDB, HLTB) don't set React keys on their injected elements.
                const PLUGIN_KEY_PREFIXES = ["romm-", "unifideck-", "hltb-", "protondb-"];
                const PLUGIN_TYPE_NAMES = ["ProtonMedal", "GameStats", "AudioLoaderCompatStateContextProvider"];
                let nativePlayIdx = -1;
                let nativeCount = 0;
                for (let i = 0; i < children.length; i++) {
                  const child = children[i];
                  const key = child?.key;
                  const typeName = child?.type?.name || child?.type?.displayName || "";
                  const isPluginByKey = key && typeof key === "string" &&
                    PLUGIN_KEY_PREFIXES.some((p) => key.startsWith(p));
                  const isPluginByType = typeName && PLUGIN_TYPE_NAMES.includes(typeName);
                  if (isPluginByKey || isPluginByType) continue;
                  nativeCount++;
                  if (nativeCount === 2) {
                    nativePlayIdx = i;
                    break;
                  }
                }

                const rommPlaySection = createElement("div", {
                  key: "romm-play-section",
                  "data-romm": "true",
                  style: {
                    display: "flex",
                    alignItems: "center",
                    width: "100%",
                    padding: "16px 2.8vw",
                    boxSizing: "border-box",
                    background: "rgba(14, 20, 27, 0.33)",
                    position: "relative",
                    zIndex: 2,
                  },
                },
                  createElement(RomMPlaySection, { appId }),
                );

                if (nativePlayIdx >= 0) {
                  debugLog(`gameDetailPatch: replacing native PlaySection at index ${nativePlayIdx}`);
                  children.splice(nativePlayIdx, 1, rommPlaySection);
                } else {
                  debugLog(`gameDetailPatch: fallback, inserting at index 1`);
                  children.splice(1, 0, rommPlaySection);
                }
              }
            }

            return ret;
          },
          "RomMGameDetail",
        );

        afterPatch(routeProps, "renderFunc", patchHandler);
      }

      return tree;
    },
  );
}

export function unregisterGameDetailPatch() {
  if (gamePatch) {
    routerHook.removePatch("/library/app/:appid", gamePatch);
    gamePatch = null;
  }
}
