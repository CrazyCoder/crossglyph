#!/bin/sh
# Start CrossGlyph through Docker Compose, then report where it is available
# and where the mounted workspace lives.
root="$(cd "$(dirname "$0")" && pwd)"

# Updates cannot replace a launcher while a shell may be reading it. Apply the
# staged copy before doing any work, preserving the outgoing one for recovery.
if [ -f "$0.staged" ]; then
    cp -p "$0" "$0.previous" 2>/dev/null || :
    if mv -f "$0.staged" "$0" 2>/dev/null; then
        chmod +x "$0" 2>/dev/null || :
        exec "$0" "$@"
    fi
fi

usage() {
    cat <<'EOF'
usage: crossglyph-docker.sh [--local]

Start CrossGlyph with its published image. Use --local to build the image from
the checkout, or from the matching version inside an unpacked release.
EOF
}

local_build=no
case "$#:$1" in
    0:) ;;
    1:--local) local_build=yes ;;
    1:-h|1:--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

if ! docker compose version >/dev/null 2>&1; then
    cat >&2 <<'EOF'
This launcher runs CrossGlyph inside an isolated Docker container.
Docker with Compose is not available.

To use this launcher, install and start Docker:
  https://docs.docker.com/get-started/get-docker/

Or run ./crossglyph.sh to start CrossGlyph directly.
EOF
    exit 1
fi

cd "$root" || exit 1

compose() {
    if [ "$local_build" = yes ]; then
        docker compose -f compose.yaml -f compose.build.yaml "$@"
    else
        docker compose "$@"
    fi
}

if [ "$local_build" = yes ]; then
    compose up -d --build --wait
    status=$?
    command_text="docker compose -f compose.yaml -f compose.build.yaml"
else
    compose up -d --wait
    status=$?
    command_text="docker compose"
fi
[ "$status" -eq 0 ] || exit "$status"

address="$(compose port crossglyph 8000 2>/dev/null)"
container="$(compose ps -q crossglyph 2>/dev/null)"
workspace=""
if [ -n "$container" ]; then
    workspace="$(docker inspect --format '{{(index .Mounts 0).Source}}' \
                 "$container" 2>/dev/null)"
fi

printf '\nCrossGlyph is ready.\n'
if [ -n "$address" ]; then
    printf '  Open:      http://%s/\n' "$address"
fi
if [ -n "$workspace" ]; then
    printf '  Workspace: %s\n' "$workspace"
    printf '  Put TTF or OTF files there. Built families appear under cpfonts.\n'
fi
printf '\nNext commands:\n'
printf '  Follow logs: %s logs -f\n' "$command_text"
printf '  Stop:        %s down\n' "$command_text"
printf '  Clean up:    %s down --rmi all\n' "$command_text"
