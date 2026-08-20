#!/usr/bin/env bash
# Rebuild a year's CSV from NUPRC's published PDF and commit it.
#
#   ./scripts/scrape_nuprc.sh 2026 ~/JAN_TO_JULY_BOPD_xxx.pdf
#   ./scripts/scrape_nuprc.sh 2026 ~/2026-Monthly-Gas-Data_June.pdf --kind gas
#   ./scripts/scrape_nuprc.sh 2026 <pdf> --dry-run
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

if [ $# -lt 2 ]; then
    echo "usage: $0 <year> <pdf-url-or-path> [--kind gas] [--dry-run]" >&2
    echo "            [--allow-new-terminals] [--allow-fewer-months] [--allow-older]" >&2
    exit 1
fi

YEAR="$1"; SOURCE="$2"; shift 2
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
ARG="$SOURCE"
if [ -f "$SOURCE" ]; then
    MOUNT=(-v "$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE"):/input.pdf:ro")
    ARG="/input.pdf"
fi

MAIL=()
for var in SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS EMAIL_FROM ALERT_EMAIL; do
    [ -n "${!var:-}" ] && MAIL+=(-e "$var=${!var}")
done

# Arguments reach bash as positional parameters after the `_` placeholder,
# never interpolated into the -c string. Interpolating splits on whitespace,
# and these filenames are full of it: Baker Hughes ships
# "July-2026  WorldWide Rig Count Report.xlsx", two spaces included.
"${DOCKER[@]}" run --rm \
    -v "$REPO:/work" -w /work "${MOUNT[@]}" "${MAIL[@]}" \
    python:3.11-slim \
    bash -c 'pip install --quiet pymupdf && exec python scripts/scrape_nuprc.py "$@"' _ \
        --url "$ARG" --year "$YEAR" --out /work "$@"

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
echo
echo "Committed. Review with 'git show', then: git push"
