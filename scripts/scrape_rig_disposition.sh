#!/usr/bin/env bash
# Refresh the NUPRC rig disposition CSVs, and commit them.
#
#   ./scripts/scrape_rig_disposition.sh              # discover the newest
#   ./scripts/scrape_rig_disposition.sh --dry-run
#   ./scripts/scrape_rig_disposition.sh --file ~/2026_Rig_Disposition.xlsx
#
# NUPRC publishes a workbook per year with a sheet per month, so the CSVs are
# rewritten whole each time and running twice changes nothing. The cadence is
# irregular -- the 2026 file covered January to March when this was written --
# so this runs monthly and simply finds nothing new most of the time.
#
# openpyxl reads the workbooks and is installed into a throwaway container
# rather than onto the host. The script itself is standard library only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSVS=("rig_disposition_nigeria.csv" "rig_disposition_summary.csv")

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

# A local workbook is mounted so the container can see it. Arguments are never
# interpolated into a shell string: NUPRC filenames carry spaces and the Baker
# Hughes ones carry double spaces, which word-splitting would tear apart.
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
    case "$arg" in
        --file) expect_path=1 ;;
    esac
    ARGS+=("$arg")
done

SCRAPER_IMAGE="nui-scraper:latest"
if ! "${DOCKER[@]}" image inspect "$SCRAPER_IMAGE" >/dev/null 2>&1; then
    echo "building $SCRAPER_IMAGE (first run only)" >&2
    "${DOCKER[@]}" build -q -f "$REPO/scripts/scraper.Dockerfile" -t "$SCRAPER_IMAGE" "$REPO/scripts" >/dev/null
fi

"${DOCKER[@]}" run --rm \
    -v "$REPO:/work" -w /work "${MOUNT[@]}" \
    "$SCRAPER_IMAGE" \
    bash -c 'exec python scripts/scrape_rig_disposition.py "$@"' _ \
        --out /work "${ARGS[@]}"

for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && exit 0
done

# The container runs as root, so the CSVs it wrote are root-owned. Committing
# as root is NOT the fix: that leaves root-owned objects in .git and every
# later pull dies with "insufficient permission for adding an object to
# repository database". Take the files back, and keep git as the invoking user.
for csv in "${CSVS[@]}"; do
    if [ -e "$REPO/$csv" ] && [ ! -O "$REPO/$csv" ]; then
        sudo chown "$(id -u):$(id -g)" "$REPO/$csv" || {
            echo "could not take $csv back from root; not committing" >&2
            exit 1
        }
    fi
done

cd "$REPO"
if git diff --quiet -- "${CSVS[@]}"; then
    echo "rig disposition unchanged, nothing to commit"
    exit 0
fi

git add "${CSVS[@]}"
git commit -m "Rig disposition: refresh from NUPRC"

if [ -n "$PUSH" ]; then
    git push
    echo "Committed and pushed."
else
    echo
    echo "Committed. Review with 'git show', then: git push"
fi
