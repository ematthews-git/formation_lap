#!/usr/bin/env bash
#
# Runs a formation-data scheduled job on the VM using the SAME Docker image as the
# API (ghcr.io/ematthews-git/formation-api), which already bundles the formation-data
# CLI and its pinned deps. Each invocation is an ephemeral `docker run --rm` container,
# so its memory is reclaimed as soon as the job exits — important on the 1 GB VM.
#
# These jobs moved off GitHub Actions because F1's livetiming API blocks GitHub's
# datacenter IPs; the VM's IP is not blocked. Config is reused from the API's .env
# (DATABASE_URL), and the FastF1 cache is mounted from the host so runs are resumable
# and stay within the livetiming rate-limit budget (cached fetches don't count).
#
# Invoked by the systemd timers in deploy/systemd/, which mirror the old cron table
# in .github/workflows/scheduled-data.yml.
#
# Usage: run-data-job.sh <weather|post-race|post-session|pre-season>
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root (~/formation_lap)

IMAGE="ghcr.io/ematthews-git/formation-api:latest"
CACHE_DIR="$PWD/fastf1_cache"
mkdir -p "$CACHE_DIR"

run() {
  docker run --rm \
    --env-file .env \
    -e FASTF1_CACHE_DIR=/cache \
    -v "$CACHE_DIR:/cache" \
    "$IMAGE" \
    uv run --no-sync --package formation-data formation-data "$@"
}

# Mirrors the `case` dispatch in scheduled-data.yml so the two stay in lockstep.
case "${1:-}" in
  weather)      run run-weather ;;
  post-race)    run run-post-race; run run-prelim --source db ;;
  post-session) run run-post-session --source db ;;
  pre-season)   run run-pre-season --season "$(date -u +%Y)" ;;
  *) echo "usage: $(basename "$0") <weather|post-race|post-session|pre-season>" >&2; exit 2 ;;
esac
