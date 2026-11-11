#!/usr/bin/env bash
#
# Runs a formation-data scheduled job on the old MacBook using the SAME Docker image as
# the API (ghcr.io/ematthews-git/formation-api), which already bundles the formation-data
# CLI and its pinned deps. Each invocation is an ephemeral `docker run --rm` container, so
# its memory is reclaimed as soon as the job exits.
#
# These jobs moved off GitHub Actions (and off the Oracle VM) because F1's livetiming API
# blocks datacenter IP ranges — both GitHub's runners and the VM sit on one. This machine's
# home/residential IP is not blocked. Config is reused from the API's .env (DATABASE_URL),
# and the FastF1 cache is mounted from the host so runs are resumable and stay within the
# livetiming rate-limit budget (cached fetches don't count).
#
# Invoked by the launchd agents in deploy/launchd/, which mirror the old cron table in
# .github/workflows/scheduled-data.yml (now dispatch-only — see that file's header).
#
# F1TV sign-in: since Oct 2026 F1's timing archive needs an F1TV Access token. Put
# F1_USERNAME and F1_PASSWORD in .env and FastF1 signs in on its own whenever the token
# (valid ~4 days) runs out. The token is kept in $AUTH_DIR on the host, so these
# throwaway containers reuse it instead of signing in on every run. `f1tv-login` signs in
# interactively instead (then re-run it every ~4 days if the credentials aren't in .env).
#
# Usage: run-data-job.sh <weather|post-race|post-session|pre-season|f1tv-login|f1tv-status>
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

# launchd invokes agents with a minimal PATH that doesn't include Docker's CLI symlink.
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

IMAGE="ghcr.io/ematthews-git/formation-api:latest"
CACHE_DIR="$PWD/fastf1_cache"
AUTH_DIR="$PWD/fastf1_auth"   # FastF1's F1TV token (gitignored, owner-only)
mkdir -p "$CACHE_DIR" "$AUTH_DIR"
chmod 700 "$AUTH_DIR"

run() {
  # FastF1 keeps its token under $XDG_DATA_HOME/fastf1; point that at the host mount.
  # (The ${a[@]+...} form keeps macOS's bash 3.2 happy with an empty array under `set -u`.)
  docker run --rm ${DOCKER_TTY_FLAGS[@]+"${DOCKER_TTY_FLAGS[@]}"} \
    --env-file .env \
    -e FASTF1_CACHE_DIR=/cache \
    -e XDG_DATA_HOME=/fastf1-data \
    -v "$CACHE_DIR:/cache" \
    -v "$AUTH_DIR:/fastf1-data" \
    "$IMAGE" \
    uv run --no-sync --package formation-data formation-data "$@"
}

DOCKER_TTY_FLAGS=()

# Mirrors the `case` dispatch in scheduled-data.yml so the two stay in lockstep.
case "${1:-}" in
  weather)      run run-weather ;;
  post-race)    run run-post-race; run run-prelim --source db ;;
  post-session) run run-post-session --source db ;;
  pre-season)   run run-pre-season --season "$(date -u +%Y)" ;;
  f1tv-login)   DOCKER_TTY_FLAGS=(-it); run f1tv login ;;
  f1tv-status)  run f1tv status ;;
  *) echo "usage: $(basename "$0") <weather|post-race|post-session|pre-season|f1tv-login|f1tv-status>" >&2; exit 2 ;;
esac
