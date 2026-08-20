#!/usr/bin/env bash
# Rebuild a year's CSV from NUPRC's published PDF and commit it.
#
#   ./scripts/scrape_nuprc.sh 2026                     # discovers the newest
#   ./scripts/scrape_nuprc.sh 2026 --kind gas
#   ./scripts/scrape_nuprc.sh 2026 ~/JAN_TO_JULY_BOPD_xxx.pdf
#   ./scripts/scrape_nuprc.sh 2026 --dry-run
#
# The report is cumulative: the July release carries January through July, so
# the newest one supersedes every earlier month, revisions included. Always
# pass the latest, and let the script rewrite the whole year.
#
# pymupdf reads the PDF and is installed into a throwaway container rather
# than onto the host, since this runs once a month. Nothing else is needed:
# the script itself is standard library only.
#
# When a guard stops the run, the script emails an alert if SMTP_* is in the
# environment. A clean run sends nothing: an alert that arrives every month is
# one nobody reads. Easiest way to supply them is the app's own env file:
#     set -a; . /home/ubuntu/nui-terminal/.env; set +a
set -euo pipefail

usage() {
    echo "usage: $0 [year] [pdf-url-or-path] [--kind gas] [--push] [--dry-run]" >&2
    echo "          [--allow-new-terminals] [--allow-fewer-months] [--allow-older]" >&2
    echo >&2
    echo "  With no year, the current one. With no PDF, the newest is" >&2
    echo "  discovered from NUPRC's catalogue. --push is for unattended runs." >&2
    exit 1
}
[ "${1:-}" = "--help" ] && usage

# The year is optional, and only a bare four-digit argument is taken as one,
# so an unattended crontab needs no calendar arithmetic -- a literal year
# there silently stops working on 1 January.
YEARARG=()
YEAR="$(date +%Y)"
if [[ "${1:-}" =~ ^[0-9]{4}$ ]]; then
    YEAR="$1"; YEARARG=(--year "$YEAR"); shift
fi
# The PDF is optional. Anything starting with a dash is a flag, so only a
# bare argument is taken as a file or URL -- which is what lets the
# unattended form be just "<year> --kind gas".
SOURCE=""
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    SOURCE="$1"; shift
fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Docker needs root unless the invoking user is in the docker group. Asked
# rather than assumed: on the NUI VM the login user is not in it, and a bare
# `docker run` there fails with "permission denied while trying to connect to
# the docker API", which reads like a docker fault rather than a permissions
# one. DOCKER_CMD overrides for testing.
if [ -n "${DOCKER_CMD:-}" ]; then
    read -r -a DOCKER <<< "$DOCKER_CMD"
elif docker info >/dev/null 2>&1; then
    DOCKER=(docker)
else
    echo "docker needs elevation here, using sudo" >&2
    DOCKER=(sudo docker)
fi

# A local PDF has to be visible from inside the container, so it is mounted
# alongside the repo rather than assumed to be reachable by the same path.
MOUNT=()
URLARG=()
if [ -n "$SOURCE" ]; then
    if [ -f "$SOURCE" ]; then
        MOUNT=(-v "$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE"):/input.pdf:ro")
        URLARG=(--url /input.pdf)
    else
        URLARG=(--url "$SOURCE")
    fi
fi

# --push is ours, not the Python script's, so it is filtered out before the
# arguments are handed on.
PUSH=""
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--push" ]; then PUSH=1; else ARGS+=("$arg"); fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"


MAIL=()
for var in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS EMAIL_FROM ALERT_EMAIL; do
    [ -n "${!var:-}" ] && MAIL+=(-e "$var=${!var}")
done

# Arguments reach bash as positional parameters after the `_` placeholder,
# never interpolated into the -c string. Interpolating splits on whitespace,
# and these filenames are full of it: Baker Hughes ships
# "July-2026  WorldWide Rig Count Report.xlsx", two spaces included.
# Built once and reused. Rebuild by deleting the image, or with
#   docker build -f scripts/scraper.Dockerfile -t $SCRAPER_IMAGE scripts/
SCRAPER_IMAGE="nui-scraper:latest"
if ! "${DOCKER[@]}" image inspect "$SCRAPER_IMAGE" >/dev/null 2>&1; then
    echo "building $SCRAPER_IMAGE (first run only)" >&2
    "${DOCKER[@]}" build -q -f "$REPO/scripts/scraper.Dockerfile" -t "$SCRAPER_IMAGE" "$REPO/scripts" >/dev/null
fi

"${DOCKER[@]}" run --rm \
    -v "$REPO:/work" -w /work "${MOUNT[@]}" "${MAIL[@]}" \
    "$SCRAPER_IMAGE" \
    bash -c 'exec python scripts/scrape_nuprc.py "$@"' _ \
        "${YEARARG[@]}" --out /work "${URLARG[@]}" "$@"

# --dry-run writes nothing, so there is nothing to commit and git would fail
# the whole script on an empty commit.
for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && exit 0
done

# Which CSV was rebuilt, so the right file is staged.
KIND="oil"
for arg in "$@"; do
    [ "$arg" = "gas" ] && KIND="gas"
done
CSV="${KIND}_${YEAR}.csv"

# The container runs as root, so whatever it wrote into the bind mount is
# owned by root. Committing as root is NOT the fix: that leaves root-owned
# objects in .git and every later pull dies with "insufficient permission for
# adding an object to repository database". Take the files back instead, and
# keep git as the invoking user.
for f in "$CSV" ".nuprc_sources.json"; do
    if [ -e "$REPO/$f" ] && [ ! -O "$REPO/$f" ]; then
        sudo chown "$(id -u):$(id -g)" "$REPO/$f" || {
            echo "could not take $f back from root; not committing" >&2
            exit 1
        }
    fi
done

cd "$REPO"
if git diff --quiet -- "$CSV"; then
    echo "$CSV unchanged, nothing to commit"
    exit 0
fi

git add "$CSV" .nuprc_sources.json
git commit -m "${YEAR}: rebuild ${KIND} from the NUPRC report"

if [ -n "$PUSH" ]; then
    git push
    echo "Committed and pushed."
else
    echo
    echo "Committed. Review with 'git show', then: git push"
fi
