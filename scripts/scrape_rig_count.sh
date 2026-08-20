#!/usr/bin/env bash
# Refresh rig_count_nigeria.csv from Baker Hughes, and commit it.
#
#   ./scripts/scrape_rig_count.sh                      # discover the newest
#   ./scripts/scrape_rig_count.sh --dry-run
#   ./scripts/scrape_rig_count.sh --url ~/July-2026.xlsx
#
# Baker Hughes publishes monthly, in the first week of the following month --
# most often the 7th, always a Friday, since the counts are Friday-based. The
# workbook carries every month it has, so the CSV is rewritten whole each time
# and running twice changes nothing.
#
# openpyxl reads the workbook and is installed into a throwaway container
# rather than onto the host, since this runs once a month. The script itself
# is standard library only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSV="rig_count_nigeria.csv"

# Docker needs root unless the invoking user is in the docker group. Asked
# rather than assumed: on the NUI VM the login user is not in it, and a bare
# `docker run` there fails with "permission denied while trying to connect to
# the docker API", which reads like a docker fault rather than a permissions
# one. DOCKER_CMD overrides it, which is how this gets tested without docker.
if [ -n "${DOCKER_CMD:-}" ]; then
    read -r -a DOCKER <<< "$DOCKER_CMD"
elif docker info >/dev/null 2>&1; then
    DOCKER=(docker)
else
    echo "docker needs elevation here, using sudo" >&2
    DOCKER=(sudo docker)
fi

# A local workbook is mounted so the container can see it. Its name is exactly
# why arguments are never interpolated into a shell string below: Baker Hughes
# ships "July-2026  WorldWide Rig Count Report.xlsx", double space included.
# --push is ours, not the Python script's, so it is filtered out below.
PUSH=""
MOUNT=()
ARGS=()
expect_path=""
for arg in "$@"; do
    if [ "$arg" = "--push" ]; then PUSH=1; expect_path=""; continue; fi
    if [ -n "$expect_path" ] && [ -f "$arg" ]; then
        dir="$(cd "$(dirname "$arg")" && pwd)"
        target="/input_${#ARGS[@]}.xlsx"
        MOUNT+=(-v "$dir/$(basename "$arg"):$target:ro")
        ARGS+=("$target")
        expect_path=""
        continue
    fi
    expect_path=""
    # --url and --history can each name a local file; both are remapped.
    case "$arg" in
        --url|--history) expect_path=1 ;;
    esac
    ARGS+=("$arg")
done

# Arguments reach bash as positional parameters after the `_` placeholder,
# never interpolated into the -c string, so spaces in a filename survive.

# Built once and reused. Rebuild by deleting the image, or with
#   docker build -f scripts/scraper.Dockerfile -t $SCRAPER_IMAGE scripts/
SCRAPER_IMAGE="nui-scraper:latest"
if ! "${DOCKER[@]}" image inspect "$SCRAPER_IMAGE" >/dev/null 2>&1; then
    echo "building $SCRAPER_IMAGE (first run only)" >&2
    "${DOCKER[@]}" build -q -f "$REPO/scripts/scraper.Dockerfile" -t "$SCRAPER_IMAGE" "$REPO/scripts" >/dev/null
fi

"${DOCKER[@]}" run --rm \
    -v "$REPO:/work" -w /work "${MOUNT[@]}" \
    "$SCRAPER_IMAGE" \
    bash -c 'exec python scripts/scrape_rig_count.py "$@"' _ \
        --out /work "${ARGS[@]}"

for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && exit 0
done

# The container runs as root, so the CSV it wrote is root-owned. Committing as
# root is NOT the fix: that leaves root-owned objects in .git and every later
# pull dies with "insufficient permission for adding an object to repository
# database". Take the file back, and keep git as the invoking user.
if [ -e "$REPO/$CSV" ] && [ ! -O "$REPO/$CSV" ]; then
    sudo chown "$(id -u):$(id -g)" "$REPO/$CSV" || {
        echo "could not take $CSV back from root; not committing" >&2
        exit 1
    }
fi

cd "$REPO"
if git diff --quiet -- "$CSV"; then
    echo "$CSV unchanged, nothing to commit"
    exit 0
fi

git add "$CSV"
git commit -m "Rig count: refresh Nigeria series from Baker Hughes"

if [ -n "$PUSH" ]; then
    git push
    echo "Committed and pushed."
else
    echo
    echo "Committed. Review with 'git show', then: git push"
fi
