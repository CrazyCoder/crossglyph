#!/bin/sh
# Assert the polyglot wrappers keep their mixed line endings: a CRLF header,
# an LF bash body, a CRLF batch body. Making either half uniform breaks one of
# the two interpreters, and most editors do it silently and show no diff.
#
# POSIX shell and nothing else, so the pre-commit hook runs it wherever git
# runs: `read` and `printf` are all it needs.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
cr="$(printf '\r')"
status=0

# $1 the file, relative to the repository root
# $2 "polyglot" or "batch"
check() {
    file="$1"
    kind="$2"
    line_number=0
    region=header
    while IFS= read -r line || [ -n "$line" ]; do
        line_number=$((line_number + 1))
        case "$line" in
            *"$cr") ending=crlf; bare="${line%"$cr"}" ;;
            *)      ending=lf;   bare="$line" ;;
        esac
        if [ "$kind" = batch ]; then
            want=crlf
        else
            case "$region" in
                header)
                    want=crlf
                    [ "$bare" = "::CMDLITERAL" ] && region=bash
                    ;;
                bash)
                    # :CMDSCRIPT is the first line cmd.exe reads again, so it
                    # belongs to the batch half rather than the bash one.
                    if [ "$bare" = ":CMDSCRIPT" ]; then
                        want=crlf
                        region=batch
                    else
                        want=lf
                    fi
                    ;;
                batch) want=crlf ;;
            esac
        fi
        if [ "$ending" != "$want" ]; then
            echo "$file:$line_number: $ending line ending where $want is required" >&2
            status=1
            return 0
        fi
    done < "$root/$file"
}

check tools/uv.cmd polyglot
# tool-wrapper.cmd is not polyglot: its shell counterpart is a separate file,
# so it is an ordinary batch file and CRLF throughout.
check tools/tool-wrapper.cmd batch
check crossglyph-docker.cmd batch

if [ "$status" -eq 0 ]; then
    echo "line endings ok"
fi
exit "$status"
