/**
 * The optional outermost layer of a firing announcement: an OS notification
 * that reaches the operator when Bisque is open but unwatched.
 *
 * **Not** with the tab closed. Nothing observes the kiln once the page is gone
 * — the announcement is driven by the live WebSocket in
 * `hooks/useFiringAnnouncements.ts`, and there is no service worker and no push
 * subscription to stand in for it. Any copy that implies otherwise invites an
 * operator to close the tab and wait for an alert that is never coming.
 *
 * Optional because it is also the one layer that cannot be relied on:
 *
 *   - The Notification API is **secure-context only**, and the firmware serves
 *     the UI over plain HTTP on a LAN IP (there is no TLS anywhere in
 *     `components/web_server/`). So `window.Notification` is `undefined` for
 *     the primary deployment. It exists on the GitHub Pages demo and on
 *     localhost.
 *   - Chrome on Android throws `Illegal constructor` for `new Notification()`;
 *     it requires `ServiceWorkerRegistration.showNotification()`, and this app
 *     registers no service worker. The constructor's *presence* therefore says
 *     nothing about delivery, which is why posting reports success or failure
 *     instead of swallowing it — see `post()`.
 *
 * Every entry point degrades rather than throws, and the toast and tab title in
 * `hooks/useFiringAnnouncements.ts` carry the feature on their own.
 *
 * The opt-in is stored per browser rather than in the firmware's
 * `notificationsEnabled`, because permission is per browser: muting Bisque on
 * one phone must not silence the kiln's webhook for every other client.
 * Storage is injected and every access wrapped, as in `utils/theme.ts` —
 * Safari's private mode throws outright on `localStorage`.
 */

import type { FiringAnnouncement } from "./firingAnnouncement";

export const NOTIFY_STORAGE_KEY = "bisque.notifications";

/** The slice of `window` this module touches, so tests need no jsdom shim. */
export interface NotificationWindow {
  Notification?: {
    new (title: string, options?: NotificationOptions): unknown;
    permission: NotificationPermission;
    requestPermission(): Promise<NotificationPermission>;
  };
}

/**
 * Whether this origin has the Notification API at all.
 *
 * False over plain HTTP, which is what keeps the Settings opt-in from
 * appearing on the device — a switch that could never do anything is worse
 * than no switch.
 */
export function notificationsSupported(win: NotificationWindow | undefined): boolean {
  return typeof win?.Notification === "function";
}

/** The browser's current permission, or `null` when unsupported — not "denied". */
export function notificationPermission(
  win: NotificationWindow | undefined,
): NotificationPermission | null {
  return notificationsSupported(win) ? win!.Notification!.permission : null;
}

/**
 * Prompt for permission. Call only from a user gesture — Safari refuses
 * otherwise, and a prompt raised by a background status change at 3am would be
 * hostile even where it is allowed.
 *
 * Resolves `null` when unsupported or when the prompt itself rejects, so the
 * caller has one "no answer" case to handle.
 */
export async function requestNotificationPermission(
  win: NotificationWindow | undefined,
): Promise<NotificationPermission | null> {
  if (!notificationsSupported(win)) return null;
  try {
    return await win!.Notification!.requestPermission();
  } catch {
    return null;
  }
}

/** Read the opt-in. Off by default; tolerates junk and a storage that throws. */
export function readNotifyPreference(storage: Pick<Storage, "getItem"> | undefined): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(NOTIFY_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

/** Persist the opt-in. Silently no-ops if storage is unavailable. */
export function writeNotifyPreference(
  storage: Pick<Storage, "setItem"> | undefined,
  on: boolean,
): void {
  if (!storage) return;
  try {
    storage.setItem(NOTIFY_STORAGE_KEY, on ? "true" : "false");
  } catch {
    /* a notification preference is not worth throwing over */
  }
}

/**
 * Both gates, in one place: the user asked for these, and the browser allows
 * them. Tab visibility is deliberately not a gate — a finished firing is worth
 * an OS notification even with the tab in front of you, because "in front of
 * you" and "being looked at" are not the same thing across a twelve-hour firing.
 */
export function shouldNotify(args: {
  enabled: boolean;
  permission: NotificationPermission | null;
}): boolean {
  return args.enabled && args.permission === "granted";
}

/**
 * One tag for every notification this app posts, so a second firing replaces
 * the first rather than stacking a week of completions in the shade.
 */
const FIRING_TAG = "bisque-firing";

/**
 * Post a notification, reporting whether the browser actually built one.
 *
 * The boolean is the point. `notificationsSupported()` can only see that a
 * constructor exists, and on Chrome for Android one does while `new
 * Notification()` throws — the platform requires
 * `ServiceWorkerRegistration.showNotification()`. Swallowing that silently is
 * what let the opt-in promise delivery it could never make, so the failure is
 * returned rather than absorbed and the caller decides what to say.
 */
function post(win: NotificationWindow | undefined, n: { title: string; body: string }): boolean {
  if (!notificationsSupported(win)) return false;
  try {
    new win!.Notification!(n.title, { body: n.body, tag: FIRING_TAG, icon: "icon-192.png" });
    return true;
  } catch {
    return false;
  }
}

export function showFiringNotification(
  win: NotificationWindow | undefined,
  announcement: FiringAnnouncement,
): boolean {
  return post(win, { title: announcement.title, body: announcement.body });
}

/**
 * Confirm the opt-in with a real notification — which doubles as the only
 * honest test that this browser can deliver one at all.
 *
 * There is no way to know before trying: the capability is not introspectable,
 * and probing eagerly would fire a stray notification at anyone whose
 * permission was already granted. Doing it here, once, at the moment the user
 * asks for notifications, costs nothing they did not just request and turns an
 * undetectable platform gap into an answer the switch can act on.
 */
export function confirmNotificationsWork(win: NotificationWindow | undefined): boolean {
  return post(win, {
    title: "Bisque alerts are on",
    body: "You'll get one of these when a firing completes or errors.",
  });
}
