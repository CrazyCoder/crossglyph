#!/bin/sh
# Run CrossGlyph, fetching uv on first use. With no arguments it opens the
# preview in a browser.
#
# Two layouts. A release keeps each version under versions/, with `current`
# naming the live one, so an update can add a directory and rewrite one line
# rather than overwrite anything. A clone or a source download has the project
# at the root and is run where it stands.
root="$(cd "$(dirname "$0")" && pwd)"

# An update leaves a new launcher beside this one rather than writing over it,
# and this is where it lands. A shell reads a script as it runs it, the same
# way cmd.exe does, so a file rewritten in place under a running shell is read
# from the wrong offset: measured, not assumed, and it duplicated two lines
# before failing. Replacing it by rename is safe here because the running
# shell keeps the file it opened, and exec leaves nothing to read anyway. The
# same staging is used on both platforms because cmd.exe needs it, and one
# mechanism is one thing to understand.
if [ -f "$0.staged" ]; then
    # Kept, so a release that shipped a broken launcher is a rename away from
    # being undone rather than a reinstall.
    cp -p "$0" "$0.previous" 2>/dev/null || :
    mv -f "$0.staged" "$0"
    chmod +x "$0" 2>/dev/null || :
    exec "$0" "$@"
fi

if [ -f "$root/current" ] && [ -d "$root/versions" ]; then
    version="$(head -n 1 "$root/current" | tr -d ' \t\r\n')"
    # Both halves of this matter. An empty `current` is what an interrupted
    # write leaves, and it names versions/ itself -- a directory that does
    # exist, so testing only for one would find it and hand uv a project that
    # is really the folder the projects live in.
    dir=""
    if [ -n "$version" ] && [ -d "$root/versions/$version" ]; then
        dir="$root/versions/$version"
    else
        # Recovery, not selection: `current` should always name a directory
        # that is there. Plain sort rather than sort -V, which older BSD sort
        # does not have -- with two versions present this can pick 0.9 over
        # 0.10, and the warning is what makes that visible.
        dir="$(ls -1d "$root"/versions/*/ 2>/dev/null | sort | tail -n 1)"
        if [ -z "$dir" ]; then
            echo "no version is installed under $root/versions" >&2
            exit 1
        fi
        echo "warning: current names ${version:-nothing}, which is not there." \
             "Using $dir" >&2
    fi
    CROSSGLYPH_HOME="$root"
    export CROSSGLYPH_HOME
    # Only when nobody has chosen one: $CROSSGLYPH_FONTS names another
    # workspace, and that is a decision the launcher must not overwrite.
    if [ -z "${CROSSGLYPH_FONTS:-}" ]; then
        CROSSGLYPH_FONTS="$root/fonts"
        export CROSSGLYPH_FONTS
    fi
elif [ -f "$root/pyproject.toml" ]; then
    # A checkout or a source download: fonts/ is already beside src/, so
    # nothing has to be said about where it is.
    dir="$root"
else
    echo "this does not look like a CrossGlyph install: $root" >&2
    exit 1
fi

exec "$dir/tools/uv.cmd" run --project "$dir" crossglyph "$@"
