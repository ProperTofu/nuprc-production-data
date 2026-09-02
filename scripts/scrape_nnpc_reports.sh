#!/usr/bin/env bash
# Refresh the NNPC monthly report CSVs, and commit them.
#
#   ./scripts/scrape_nnpc_reports.sh              # current year
#   ./scripts/scrape_nnpc_reports.sh --dry-run
#   ./scripts/scrape_nnpc_reports.sh --year 2025
#
# NNPC publish one summary page a month and it carries a twelve-month
# history, so a run mostly re-confirms what is already here. The July 2026
# report was uploaded on 31 August, which is the cadence to expect: late in
# the month following. Running monthly on the 1st therefore catches it, and
# a second run mid-month costs one listing request if it slipped.
#
# pymupdf reads the PDFs and is already in the scraper image. The script
# itself is standard library only.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS=("nnpc_monthly_production.csv" "nnpc_report_headline.csv" \
         "nnpc_reports_manifest.json")

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

PUSH=""
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--push" ]; then PUSH=1; continue; fi
    ARGS+=("$arg")
done

SCRAPER_IMAGE="nui-scraper:latest"
if ! "${DOCKER[@]}" image inspect "$SCRAPER_IMAGE" >/dev/null 2>&1; then
    echo "building $SCRAPER_IMAGE (first run only)" >&2
    "${DOCKER[@]}" build -q -f "$REPO/scripts/scraper.Dockerfile" -t "$SCRAPER_IMAGE" "$REPO/scripts" >/dev/null
fi

"${DOCKER[@]}" run --rm \
    -v "$REPO:/work" -w /work \
    "$SCRAPER_IMAGE" \
    bash -c 'exec python scripts/scrape_nnpc_reports.py "$@"' _ \
        --out /work ${ARGS[@]+"${ARGS[@]}"}

for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && exit 0
done

# The container runs as root, so the files it wrote are root-owned.
# Committing as root is NOT the fix: that leaves root-owned objects in .git
# and every later pull dies with "insufficient permission for adding an
# object to repository database". Take the files back, keep git as the
# invoking user.
for f in "${OUTPUTS[@]}"; do
    if [ -e "$REPO/$f" ] && [ ! -O "$REPO/$f" ]; then
        sudo chown "$(id -u):$(id -g)" "$REPO/$f" || {
            echo "could not take $f back from root; not committing" >&2
            exit 1
        }
    fi
done

cd "$REPO"
if git diff --quiet -- "${OUTPUTS[@]}"; then
    echo "NNPC reports unchanged, nothing to commit"
    exit 0
fi

# Name the new report in the commit when there is one, so `git log` says
# what arrived rather than only that something did.
# The manifest often does not change when a CSV does -- a run that revises
# figures without adding a document is the normal case. `grep` then finds
# nothing and exits 1, `pipefail` propagates that, and `set -e` kills the
# script HERE, after the scraper has already done its work and before
# anything is committed. It exits 1 with no message at all, which reads as
# the scraper failing when the scraper succeeded. `|| true` because an
# empty result is a legitimate answer: nothing new arrived.
NEW="$(git diff -- nnpc_reports_manifest.json | grep -oE '"NNPC[A-Za-z0-9_]+\.pdf"' | head -1 | tr -d '"' || true)"
if [ -n "$NEW" ]; then
    MSG="NNPC monthly report: add $NEW"
else
    MSG="NNPC monthly reports: refresh"
fi

git add "${OUTPUTS[@]}"
git commit -m "$MSG"

if [ -n "$PUSH" ]; then
    git push
    echo "Committed and pushed."
else
    echo
    echo "Committed. Review with 'git show', then: git push"
fi
