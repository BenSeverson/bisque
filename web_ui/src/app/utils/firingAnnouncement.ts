/**
 * The one moment in a firing worth interrupting someone for.
 *
 * A firing runs 8–14 hours. Until #185 the transition into `complete` or
 * `error` repainted a badge and nothing else — so the single instant an
 * operator actually needs to know about was the one the UI kept to itself,
 * visible only to whoever happened to be looking at the tab.
 *
 * This module decides *whether* a status change is that moment, and *what* to
 * say. It deliberately knows nothing about toasts, tab titles or the
 * Notification API; `hooks/useFiringAnnouncements.ts` owns the delivery.
 */

import type { FiringStatus } from "../types/kiln";

/** `<title>` when nothing has happened. Mirrors `index.html`. */
export const BASE_TAB_TITLE = "Bisque";

export type AnnouncementKind = "complete" | "error";

export interface FiringAnnouncement {
  kind: AnnouncementKind;
  /** Toast heading, and the OS notification's title. */
  title: string;
  /** Toast description, and the OS notification's body. */
  body: string;
  /** Replaces `document.title` while the tab is in the background. */
  tabTitle: string;
}

/*
 * The copy stays generic on purpose.
 *
 * The error *cause* is not on the status feed — it lives on /api/v1/system and
 * has to be fetched after the transition, which is the whole reason
 * `errorCodeForTransition()` exists to referee stale payloads. Naming a cause
 * here would mean either racing that fetch or announcing the *previous*
 * failure's reason. The dashboard's error banner is the surface that names the
 * fault; this is the surface that gets the operator to look at it.
 */
const ANNOUNCEMENTS: Record<AnnouncementKind, FiringAnnouncement> = {
  complete: {
    kind: "complete",
    title: "Firing complete",
    body: "The programme finished. Let the kiln cool before opening it.",
    tabTitle: `✓ Firing complete — ${BASE_TAB_TITLE}`,
  },
  error: {
    kind: "error",
    title: "Firing stopped",
    body: "The kiln reported a fault and stopped heating. Open Bisque for the cause.",
    tabTitle: `⚠ Firing stopped — ${BASE_TAB_TITLE}`,
  },
};

/**
 * Is moving from `prev` to `next` an event worth announcing?
 *
 * Both arguments are nullable, and both nulls mean the same thing: **nothing
 * has been observed yet**. That is load-bearing rather than defensive.
 *
 * The firmware holds `FIRING_STATUS_COMPLETE` until the next start or stop
 * (`complete_firing()` in `firing_engine.c`), so the mount-time `/api/v1/status`
 * seed routinely lands on `complete` hours after the firing ended. Announcing
 * that would re-fire last night's completion on every page load, every morning,
 * forever.
 *
 * The subtlety — and the bug this shape exists to prevent — is that the store
 * *starts* at a synthetic `idle`, so "the status the hook saw on its first
 * render" is not an observation. Passing `null` for `next` until the store has
 * actually heard from the controller is what keeps that placeholder from being
 * mistaken for a baseline and turning the first real reading into a transition.
 *
 * Everything else falls out: the first genuine observation only establishes the
 * baseline, a terminal status repeated across frames is not a transition, and
 * `complete` → `error` is one, because a fault after a completion is news.
 */
export function announcementFor(
  prev: FiringStatus | null,
  next: FiringStatus | null,
): FiringAnnouncement | null {
  if (next === null || prev === null || prev === next) return null;
  if (next !== "complete" && next !== "error") return null;
  return ANNOUNCEMENTS[next];
}
