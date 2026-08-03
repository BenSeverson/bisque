import { describe, it, expect, vi } from "vitest";
import {
  NOTIFY_STORAGE_KEY,
  notificationPermission,
  notificationsSupported,
  readNotifyPreference,
  requestNotificationPermission,
  shouldNotify,
  showFiringNotification,
  writeNotifyPreference,
  type NotificationWindow,
} from "./browserNotifications";
import { announcementFor } from "./firingAnnouncement";

function memoryStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}

const throwingStorage = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("SecurityError");
  },
};

/** A window whose Notification constructor records what it was handed. */
function fakeWindow(
  permission: NotificationPermission = "granted",
  ctor: (title: string, options?: NotificationOptions) => void = () => {},
): NotificationWindow & { requested: number } {
  const win = {
    requested: 0,
    Notification: Object.assign(
      class {
        constructor(title: string, options?: NotificationOptions) {
          ctor(title, options);
        }
      },
      {
        permission,
        requestPermission: async () => {
          win.requested += 1;
          return permission;
        },
      },
    ),
  };
  return win as unknown as NotificationWindow & { requested: number };
}

const announcement = announcementFor("heating", "complete")!;

describe("notificationsSupported", () => {
  // The firmware serves the UI over plain HTTP on a LAN IP, and the Notification
  // API is secure-context only — so this is `false` for the primary deployment,
  // and is what hides the Settings opt-in there.
  it("is false when the API is absent, as on a plain-HTTP origin", () => {
    expect(notificationsSupported({})).toBe(false);
  });

  it("is false for an undefined window", () => {
    expect(notificationsSupported(undefined)).toBe(false);
  });

  it("is true when the constructor is present", () => {
    expect(notificationsSupported(fakeWindow())).toBe(true);
  });
});

describe("notificationPermission", () => {
  it("is null when unsupported, distinguishing it from a denial", () => {
    expect(notificationPermission({})).toBeNull();
  });

  it("reports the browser's current permission", () => {
    for (const p of ["granted", "denied", "default"] as const) {
      expect(notificationPermission(fakeWindow(p))).toBe(p);
    }
  });
});

describe("requestNotificationPermission", () => {
  it("returns null without prompting when unsupported", async () => {
    await expect(requestNotificationPermission({})).resolves.toBeNull();
  });

  it("forwards the browser's answer", async () => {
    const win = fakeWindow("denied");
    await expect(requestNotificationPermission(win)).resolves.toBe("denied");
    expect(win.requested).toBe(1);
  });

  it("resolves to null when the prompt itself rejects", async () => {
    const win = {
      Notification: Object.assign(class {}, {
        permission: "default" as NotificationPermission,
        requestPermission: async () => {
          throw new Error("nope");
        },
      }),
    } as unknown as NotificationWindow;
    await expect(requestNotificationPermission(win)).resolves.toBeNull();
  });
});

describe("shouldNotify", () => {
  it("requires both the opt-in and a granted permission", () => {
    expect(shouldNotify({ enabled: true, permission: "granted" })).toBe(true);
    expect(shouldNotify({ enabled: false, permission: "granted" })).toBe(false);
    expect(shouldNotify({ enabled: true, permission: "denied" })).toBe(false);
    expect(shouldNotify({ enabled: true, permission: "default" })).toBe(false);
    expect(shouldNotify({ enabled: true, permission: null })).toBe(false);
  });
});

describe("readNotifyPreference", () => {
  it("defaults to off — notifications are opt-in", () => {
    expect(readNotifyPreference(memoryStorage())).toBe(false);
    expect(readNotifyPreference(undefined)).toBe(false);
  });

  it("reads a stored opt-in", () => {
    expect(readNotifyPreference(memoryStorage({ [NOTIFY_STORAGE_KEY]: "true" }))).toBe(true);
  });

  it("treats a hand-edited junk value as off", () => {
    expect(readNotifyPreference(memoryStorage({ [NOTIFY_STORAGE_KEY]: "yes please" }))).toBe(false);
  });

  it("survives storage that throws, as Safari private mode does", () => {
    expect(readNotifyPreference(throwingStorage)).toBe(false);
  });
});

describe("writeNotifyPreference", () => {
  it("round-trips through storage", () => {
    const s = memoryStorage();
    writeNotifyPreference(s, true);
    expect(readNotifyPreference(s)).toBe(true);
    writeNotifyPreference(s, false);
    expect(readNotifyPreference(s)).toBe(false);
  });

  it("silently no-ops on storage that throws", () => {
    expect(() => writeNotifyPreference(throwingStorage, true)).not.toThrow();
    expect(() => writeNotifyPreference(undefined, true)).not.toThrow();
  });
});

describe("showFiringNotification", () => {
  it("passes the announcement's title and body to the constructor", () => {
    const seen = vi.fn();
    showFiringNotification(fakeWindow("granted", seen), announcement);
    expect(seen).toHaveBeenCalledTimes(1);
    const [title, options] = seen.mock.calls[0];
    expect(title).toBe(announcement.title);
    expect(options?.body).toBe(announcement.body);
    // A tag means a second firing's notification replaces the first rather than
    // stacking a week of them in the shade.
    expect(options?.tag).toBeTruthy();
  });

  // Chrome on Android throws `Illegal constructor` here — it requires
  // ServiceWorkerRegistration.showNotification(), and this app registers no
  // service worker. The toast and tab title still have to land.
  it("swallows a constructor that throws", () => {
    const win = fakeWindow("granted", () => {
      throw new TypeError("Illegal constructor");
    });
    expect(() => showFiringNotification(win, announcement)).not.toThrow();
  });

  it("does nothing when unsupported", () => {
    expect(() => showFiringNotification({}, announcement)).not.toThrow();
  });
});
