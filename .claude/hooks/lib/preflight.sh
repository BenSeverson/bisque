#!/bin/bash
# Shared network preflight for the SessionStart installers. Source, don't run.
#
# Cloud sessions run behind a network policy chosen per environment, and the
# default policy blocks the hosts the firmware and PCB toolchains install from.
# The installers therefore check reachability up front and, when something is
# blocked, tell the developer exactly which hosts to allow rather than trying to
# route around the block. Working around it is what produced a container that
# built *something* but not the same thing CI builds — see docs/cloud-dev.md.
#
# A blocked host is distinguishable from an unhealthy one: the gateway answers
# CONNECT with 403 and curl fails at the connection level (no HTTP status),
# whereas a reachable host returns *some* status — even 401/403/404 — which is
# all we need to know the policy permits it.

PREFLIGHT_TIMEOUT="${PREFLIGHT_TIMEOUT:-10}"

# preflight_probe_http <url> — reachable if the host answered at all.
#
# -L is essential, not cosmetic: the release-asset probe starts at a github.com
# URL that 302s to the CDN host whose reachability is actually being claimed.
# Without following the redirect the probe stops at github.com and reports a
# blocked asset host as fine, which is the opposite of this file's job.
preflight_probe_http() {
    curl -sSL -o /dev/null --max-time "$PREFLIGHT_TIMEOUT" "$1" >/dev/null 2>&1
}

# preflight_probe_git <repo-url> — exercises the git path specifically, which
# can differ from a plain HTTPS GET to the same host.
preflight_probe_git() {
    GIT_TERMINAL_PROMPT=0 git ls-remote --heads "$1" >/dev/null 2>&1
}

# preflight_check <log-prefix> <spec>...
#
# Each spec is "host|kind|target|why", kind being http or git. Populates the
# global PREFLIGHT_BLOCKED with one "host|why" line per unreachable host and
# returns non-zero if any were blocked.
preflight_check() {
    local prefix="$1"
    shift
    PREFLIGHT_BLOCKED=""

    local spec host kind target why
    for spec in "$@"; do
        IFS='|' read -r host kind target why <<<"$spec"
        case "$kind" in
        git) preflight_probe_git "$target" && continue ;;
        *) preflight_probe_http "$target" && continue ;;
        esac
        PREFLIGHT_BLOCKED+="${host}|${why}"$'\n'
    done

    [ -z "$PREFLIGHT_BLOCKED" ]
}

# preflight_report_blocked <log-prefix> <what-stays-unavailable>
#
# Prints the blocked hosts and how to allow them. Deliberately verbose and
# copy-pasteable: this text is the whole remedy, and it is read in a terminal
# scrollback at session start, not in a browser.
preflight_report_blocked() {
    local prefix="$1" unavailable="$2"
    local host why

    printf '%s %s\n' "$prefix" "network policy blocks the hosts below, so $unavailable"
    printf '%s %s\n' "$prefix" "is unavailable in this session:"
    printf '%s\n' ""
    while IFS='|' read -r host why; do
        [ -n "$host" ] || continue
        printf '%s     %-34s %s\n' "$prefix" "$host" "$why"
    done <<<"$PREFLIGHT_BLOCKED"
    printf '%s\n' ""
    printf '%s %s\n' "$prefix" "To fix: open the environment's settings in the Claude Code web or"
    printf '%s %s\n' "$prefix" "desktop app, allow the hosts above in its network policy, then start a"
    printf '%s %s\n' "$prefix" "new session — the policy cannot be changed from inside a running one."
    printf '%s %s\n' "$prefix" "Full host list and rationale: docs/cloud-dev.md"
}
