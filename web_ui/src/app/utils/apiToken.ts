/**
 * Longest API token the firmware can store.
 *
 * `kiln_settings_t.api_token` is `char[64]`, so 63 characters plus a NUL. The
 * firmware rejects anything longer rather than truncating: a silently truncated
 * token would leave the client authenticating with the full string the device
 * never stored.
 */
export const API_TOKEN_MAX_LENGTH = 63;

export type ApiTokenChange = { kind: "set"; token: string } | { kind: "clear" };

/**
 * Persist an API-token change, then switch the local client over to it.
 *
 * The ordering is the whole point. The save request is authenticated with the
 * token the client is *currently* using, so the client must not adopt the new
 * one until the device has accepted it. Adopting first (the previous behavior)
 * meant a rotation authenticated the save with the not-yet-saved token, took a
 * 401, and left the client using a token the device had never stored — a full
 * lockout with no recovery short of re-entering the old value.
 *
 * Clearing sends an explicit empty string, which the firmware distinguishes
 * from an omitted field ("leave unchanged").
 *
 * Rejects without saving or activating if the token is too long for the
 * firmware to hold. Rejects (leaving the client token untouched) if the save
 * itself fails; callers should surface that rather than reporting success.
 */
export async function commitApiTokenChange(
  change: ApiTokenChange,
  save: (apiToken: string) => Promise<unknown>,
  activate: (token: string | null) => void,
): Promise<void> {
  if (change.kind === "set" && change.token.length > API_TOKEN_MAX_LENGTH) {
    throw new Error(`API token is too long (max ${API_TOKEN_MAX_LENGTH} characters)`);
  }
  const next = change.kind === "set" ? change.token : "";
  await save(next);
  activate(change.kind === "set" ? change.token : null);
}
