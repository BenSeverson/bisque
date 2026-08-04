# Firing completion announcements (web UI) — design

Closes [#185](https://github.com/BenSeverson/bisque/issues/185).

## Problem

A firing runs 8–14 hours. When the status transitions to `complete` or `error`,
the web UI does nothing but repaint a badge. Nobody watches the tab that long,
so the transition — the one moment in the whole firing the operator actually
needs — passes unobserved.

The Settings "Notifications" toggle looks like it should cover this. It does
not: `notifications_enabled` gates exactly one thing, the webhook POST
(`components/web_server/api_handlers.c:154`), yet it sits in the *Safety
Settings* card two cards above the webhook URL it controls, under the copy
"Receive notifications for important events".

## Constraint discovered during design

**The Notification API is unavailable on the device.** It is gated on secure
contexts, and the firmware serves the UI over plain HTTP on a LAN IP — there is
no TLS anywhere in `components/web_server/`. So `window.Notification` is
`undefined` for the primary deployment. It is available on the GitHub Pages demo
(https) and on `localhost` during development.

Separately, Chrome on Android throws `Illegal constructor` for
`new Notification()` — it requires `ServiceWorkerRegistration.showNotification()`,
and this app registers no service worker.

Neither is a reason to drop the feature, but both mean the notification is the
*optional* layer. The toast and the tab title work everywhere and carry the
feature on their own.

## Design

### `stores/kilnStore.ts` — a new `statusObserved` flag

`firingProgress` is initialised to a plausible-looking idle kiln, so its
contents alone cannot answer "has this client ever heard from the controller?".
Both `seedFromStatus` and the WebSocket handler now set `statusObserved`.

This is not incidental. It was found by testing the reload case against the
running mock (see below) and it is the whole feature in miniature: without it,
the *synthetic* starting `idle` is mistaken for an observation, the first real
reading of `complete` looks like `idle` → `complete`, and every page load
re-announces last night's firing.

It is distinct from `lastUpdateAt`, which timestamps WebSocket frames only — a
REST seed is an observation too, and on a fresh load it is the first one.

### `src/app/utils/firingAnnouncement.ts` — pure, tested

```ts
announcementFor(prev: FiringStatus | null, next: FiringStatus | null): FiringAnnouncement | null
```

Returns `null` unless both are non-null, they differ, and `next` is `complete`
or `error`.

Both arguments are nullable and both nulls mean "nothing observed yet". The
firmware holds `FIRING_STATUS_COMPLETE` until the next start or stop
(`complete_firing()`, `firing_engine.c:737`), so a reload the morning after a
firing seeds `complete` from `/api/v1/status`. Passing `null` for `next` until
`statusObserved` is what keeps the placeholder from becoming a baseline; the
first genuine observation then establishes one silently.

Because the hook feeds this one status at a time, the tests assert on
*sequences* rather than single calls — that is the level at which "announce
once per firing, and never on a reload" is even expressible.

The returned object carries the toast heading, the body (notification body and
toast description), and the tab title.

Copy stays generic. The error *cause* lives on `/api/v1/system`, not on the
status feed, so naming it in the announcement would race the fetch that
`errorCodeForTransition()` already exists to referee. The dashboard's error
banner is the surface that names the fault.

### `src/app/utils/browserNotifications.ts` — pure, tested

- `notificationsSupported(win)` — `typeof win?.Notification === "function"`.
  False over plain HTTP, which is what hides the opt-in.
- `readNotifyPreference(storage)` / `writeNotifyPreference(storage, on)` —
  `"bisque.notifications"`, **default off**. Storage is injected and every
  access is wrapped, matching `utils/theme.ts`: Safari private mode throws on
  `localStorage`, and a notification preference is never worth breaking the app
  over.
- `notificationPermission(win)` / `requestNotificationPermission(win)`.
- `shouldNotify({ enabled, permission })` — `enabled && permission === "granted"`.
- `showFiringNotification(win, announcement)` — constructs the `Notification`
  inside a `try`/`catch`. Android Chrome throws here; swallowing it leaves the
  toast and title intact rather than taking down the announcement.

The preference is a browser-local setting rather than the firmware's
`notificationsEnabled`, because permission is per-browser: muting Bisque on one
phone must not silence the kiln's webhook for everyone.

### `src/app/hooks/useFiringAnnouncements.ts`

Called once from `App.tsx`. Watches `firingProgress.status`, holds the previous
status in a ref seeded to `null`, and on a real transition:

1. `toast.success` / `toast.error`. Completion auto-dismisses; an error toast
   uses `duration: Infinity`, so an operator returning after eight hours still
   finds it.
2. Sets `document.title` — **only when the document is hidden**. A title change
   on a tab the user is already looking at is invisible in the moment and then
   sits there stale, since nothing would fire a `visibilitychange` to release
   it. The toast is the moment for a visible tab.
3. Fires the notification when `shouldNotify` allows, regardless of tab
   visibility.

The preference is read from storage at announce time rather than held in React
state, so Settings and this hook cannot drift out of sync.

The claimed title is released when the tab next becomes visible, or when the
status leaves the terminal state — whichever happens first.

### `src/app/components/Settings.tsx`

A new **Browser Alerts** card, placed after `</form>` alongside Wi-Fi and API
Security, because it saves immediately and is not part of "Save Settings".
Rendered only when `notificationsSupported()`; otherwise a single line explains
that browser notifications need a secure (https) connection.

Permission is requested from the switch — a user gesture, which Safari requires
— never from a background transition. A `denied` result flips the switch back
and toasts that the block must be lifted in browser settings.

The firmware toggle moves out of *Safety Settings* into the *Webhook
Notifications* card and is retitled to say what it gates.

## Testing

Colocated Vitest beside each util module:

- the transition matrix, including the `null` baseline, `complete` → `complete`,
  `error` → `complete`, and every non-terminal target
- observation *sequences*: announce once per firing; silent on a reload landing
  in `complete` or `error`; still armed for the firing after that
- storage that throws on read and on write
- an absent `Notification` constructor
- `shouldNotify` across the three permission values
- `showFiringNotification` swallowing a constructor that throws

No test touches the hook directly; its logic lives in the two pure modules.

Beyond the unit tests, the flow was driven end to end against the Vite dev
server's in-process mock: a firing started, skipped to `complete`, and separately
tripped into `error` via `/api/v1/mock/fault`, checking the toast copy, the tab
title, and its release. The reload case has to be exercised there rather than in
the demo build, whose simulator state lives in the browser and resets on reload —
which is precisely why the bug survived the first round of checking.

Not covered by either: the granted-permission path. The automated browser has
notifications denied at the profile level, so only the blocked-state UI could be
observed directly.
