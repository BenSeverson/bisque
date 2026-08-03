import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useKilnStore } from "../stores/kilnStore";
import type { FiringStatus } from "../types/kiln";
import { BASE_TAB_TITLE, announcementFor } from "../utils/firingAnnouncement";
import {
  notificationPermission,
  readNotifyPreference,
  shouldNotify,
  showFiringNotification,
} from "../utils/browserNotifications";

/**
 * Long enough to survive being glanced at, short enough not to sit over the
 * dashboard of the *next* firing.
 */
const COMPLETE_TOAST_MS = 30_000;

function releaseTitle(claimed: { current: boolean }): void {
  if (!claimed.current) return;
  claimed.current = false;
  document.title = BASE_TAB_TITLE;
}

/**
 * Announce the end of a firing, in as many places as the browser allows.
 *
 * Three layers, deliberately independent — a firing takes 8–14 hours and the
 * operator could be anywhere on that spectrum of attention:
 *
 *   1. A toast, for someone with the tab in front of them.
 *   2. The tab title, for someone with it open behind a dozen others.
 *   3. An OS notification, for someone who is not at the computer at all.
 *
 * Only the third can be unavailable (see `utils/browserNotifications.ts`), and
 * the first two carry the feature without it.
 *
 * Call once, app-wide. All the decision-making lives in the two pure modules
 * this delegates to; what is left here is delivery and the tab-title lease.
 */
export function useFiringAnnouncements(): void {
  const storeStatus = useKilnStore((s) => s.firingProgress.status);
  const observed = useKilnStore((s) => s.statusObserved);

  /* The store initialises `firingProgress` to a synthetic idle kiln, so its
     status is only a *reading* once something has been folded in. Until then
     this is null, and `announcementFor` treats it as "no observation" — which
     is what stops a page loaded while the kiln sits in `complete` (held by the
     firmware until the next start) from announcing last night's firing. */
  const status = observed ? storeStatus : null;

  /* The last observed status, or null while nothing has been observed. */
  const prevStatus = useRef<FiringStatus | null>(null);
  /* Whether we replaced document.title and still owe a restore. */
  const titleClaimed = useRef(false);
  /* The live fault toast, which never expires on its own — see below. */
  const faultToast = useRef<string | number | null>(null);

  useEffect(() => {
    const prev = prevStatus.current;
    prevStatus.current = status;

    /* The fault toast opts out of its own dismissal timer, so it has to be
       retracted deliberately. Once the kiln is out of `error` — stopped, reset,
       or restarted from the LCD, the iOS app or another tab — "Firing stopped"
       is no longer a true statement, and an unattended tab would otherwise fly
       it over the whole of the next firing.

       sonner defers the removal itself to a requestAnimationFrame, which a
       hidden tab never runs, so in the background case this takes effect on the
       first frame painted after the user comes back rather than immediately.
       That is the right moment anyway — nobody was reading it in between — but
       it does mean the retraction is invisible to any test whose tab stays
       hidden, which reads as a broken dismiss. It is not. */
    if (status !== "error" && faultToast.current !== null) {
      toast.dismiss(faultToast.current);
      faultToast.current = null;
    }

    const announcement = announcementFor(prev, status);
    if (!announcement) {
      /* Leaving the terminal status — a new firing, or a stop — makes the
         claimed title a statement about something that is no longer true. */
      if (status !== "complete" && status !== "error") releaseTitle(titleClaimed);
      return;
    }

    if (announcement.kind === "error") {
      /* Sticky. Every other toast in this app reports something the user just
         did and can afford to expire; this one reports a kiln fault to someone
         who may not read it for eight hours. Held by id so the block above can
         retract it the moment it stops being true. */
      faultToast.current = toast.error(announcement.title, {
        description: announcement.body,
        duration: Infinity,
      });
    } else {
      toast.success(announcement.title, {
        description: announcement.body,
        duration: COMPLETE_TOAST_MS,
      });
    }

    /* Claimed only while the tab is in the background. On a tab the user is
       already looking at, the title is the least visible thing on screen — and
       then it would sit there stale, because nothing fires a `visibilitychange`
       for a tab that never left. The toast is the moment for a visible tab. */
    if (document.visibilityState === "hidden") {
      titleClaimed.current = true;
      document.title = announcement.tabTitle;
    }

    /* The opt-in is read here rather than held in React state, so a change made
       in Settings during this session cannot go stale behind a memo. */
    const enabled = readNotifyPreference(window.localStorage);
    if (shouldNotify({ enabled, permission: notificationPermission(window) })) {
      showFiringNotification(window, announcement);
    }
  }, [status]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") releaseTitle(titleClaimed);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
}
