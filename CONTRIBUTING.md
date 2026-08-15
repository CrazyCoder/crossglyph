# Contributing

```sh
uv sync
uv run pytest -q          # while iterating: name the file you touched
uv run pytest -n 8 -q     # the whole suite, before pushing
node --experimental-vm-modules tests/preview_persistence.mjs
```

`.python-version` pins CPython 3.12.14, so `uv sync` fetches that exact
interpreter instead of taking whichever 3.12 or later the machine happens to
have. It carries `export-ignore`, which keeps it out of the release: a checkout
and CI build and test what ships, while an install resolves against
`requires-python` and reuses an interpreter it already has. Moving a patch
digit here is no reason for everyone to download a second CPython, and uv
removes neither of them on its own.

`-n 8` is pytest-xdist and belongs on the full run only. Each worker costs about
two seconds to start, which is more than a scoped run takes at all.

The page has no browser test. `tests/preview_persistence.mjs` runs its modules
against a stub DOM in Node, which is enough to cover what the page remembers,
what it sends and when it redraws. It links them as modules, each in its own
scope, so a module that reads a name it never imported fails here rather than
on the first click. That needs `--experimental-vm-modules`, which is why the
line above carries it.

Two static checks run before any of that, because what they catch is a page
that never loads, and a page that never loads has no behaviour to test. One is
the missing import above. The other is the reason `start.js` exists: the import
graph has cycles, so a module body runs while a module it imports may still be
evaluating, and a binding read there is in its dead zone. Wiring that crosses
modules goes in `start.js`, and each module exports a `wire...` function for it
to call. A handle a module owns itself cannot be in a dead zone, so those
listeners stay in the module.

## Fonts the tests need

Almost every test builds its own faces with `tests/fontsmith.py`, which
synthesizes a font from a list of codepoints. Three kinds of test cannot:
whole-page rendering, kerning read from a real GPOS table, and stem darkening,
which only the Adobe CFF driver applies.

Those read a font off your machine, and skip when there is none. Name one and
they run:

| variable | wanted |
|---|---|
| `CROSSGLYPH_TEST_FONT` | a text face with Latin and Cyrillic |
| `CROSSGLYPH_TEST_ITALIC` | its italic |
| `CROSSGLYPH_TEST_OTF` | an OTF with a CFF outline, ligatures and a `pnum` feature |

A firmware checkout beside this one supplies NotoSans, which a few metrics
tests read directly.

Name one before believing a green run. A third of the suite is behind these,
and the synthesized faces differ from a real one in ways tests can rest on
without saying so: they are narrow, so words fit in columns a real face
overflows.

## The git hook

```sh
git config core.hooksPath .githooks
```

That is one hook, and it checks the line endings described below.

## Line endings in the wrappers

`tools/uv.cmd` is a polyglot. Bash reads the top half; `cmd.exe` jumps past it
to the bottom half. The two halves need different line endings, so the file
carries both:

```
:<<"::CMDLITERAL"          CRLF, the header cmd.exe parses
@ECHO OFF
GOTO :CMDSCRIPT
::CMDLITERAL

# bash body                LF, which bash runs and cmd.exe skips
exec "$root/tool-wrapper.sh" "$@"

:CMDSCRIPT                 CRLF, the batch body
call "%~dp0tool-wrapper.cmd"
```

Making either half uniform breaks one of the two interpreters. All LF misparses
under a double byte code page on Chinese, Japanese and Korean Windows, where
`cmd.exe` reports errors like `'etlocal' is not recognized`. It only shows up
above a certain file size, where a buffer boundary lands inside a word. All
CRLF puts carriage returns in the bash body, where they become part of the
tokens.

`.gitattributes` carries `*.cmd -text`, so git normalizes nothing on checkout
under any `core.autocrlf`. Most editors rewrite a whole file to one ending and
show no diff for it, which is why there is a checker:

```sh
sh tools/check-line-endings.sh
```

The pre-commit hook runs it when a `.cmd` file is staged. There is no repair
mode. If a wrapper is mangled, `git checkout -- tools/uv.cmd` puts the bytes
back.

Two more rules for that file. Copy an existing wrapper rather than writing one
from scratch, and never run `dos2unix` or `unix2dos` on one.

## Updating uv

```sh
uv run tools/bump-uv.py            # to uv's latest release
uv run tools/bump-uv.py 0.12.4     # to a named one
uv run tools/bump-uv.py --commit   # and commit the result
```

The version and its six checksums appear in the wrapper twice, once in each
half, and a hash copied wrong lands on the one platform nobody bumping it is
running. The script reads uv's newest tag off the redirect from its releases
page, takes the SHA-256 that astral publishes beside each archive, and swaps
those fourteen strings and nothing else. Replacing fixed substrings is what
keeps the line endings exact, and it refuses to write a file whose two halves
have come to say different things.

Then it runs the wrapper once, which downloads one archive and checks its hash
for real. A published checksum cannot do that: it says what the archive should
hash to, not that the file at that address is the one it describes. `--verify`
does the same across all six platforms, about 120 MB, and is worth the wait
before a release.

`--commit` writes `chore(tools): bump uv to <version>` for that path alone, and
refuses to start if the wrapper already has uncommitted changes, so a bump
cannot carry an unrelated edit along with it.

## Making a release

Bump the version in `pyproject.toml`, commit it, then tag and push. `X.Y.Z` in
this command stands for the version just set:

```sh
git tag vX.Y.Z && git push origin vX.Y.Z
```

The workflow does the rest: it checks that the tag and the version agree,
builds and publishes the zip and container image, and puts the manifest on
Pages. A tag that disagrees with `pyproject.toml` fails the run rather than
shipping a release that misdescribes itself.

A second workflow, `test.yml`, runs the suite and the page against Ubuntu and
Windows on every push and pull request. The release calls it before it builds
anything, so a tag cannot publish what the suite has not passed. That is a
`workflow_call` rather than a `needs:` on the job over there, because `needs`
only names jobs inside one workflow.

It drives the pinned uv through `tools/uv.cmd`, so each run verifies that
checksum on both platforms and tests on the interpreter `.python-version`
names. Two steps guard what the suite cannot say for itself: the wrappers keep
their line endings, and the faces the rendering tests need are present, since
a third of the suite skips without them and says nothing while doing it.

### The container package must be public

GitHub creates a new package under a personal account as private, even when
the source repository is public. After the first workflow publishes the image,
open **Profile > Packages > crossglyph > Package settings > Change visibility**
and select **Public**. This is a one-time setting. A private package asks Docker
users to sign in instead of allowing the anonymous pull that `compose.yaml`
uses.

The image's source label links the package to this repository before the first
push. The package then inherits repository access, and the release workflow can
publish later tags with its `packages: write` permission.

### Pages has to admit the tag

Two things about Pages have to be true before the first tag, and neither says
so when it is not.

Pages must be turned on with GitHub Actions as the source. The manifest is
deployed after the release is published, so without it a tag creates the
release and then fails, leaving something no install can discover and a rerun
that stops at "release already exists".

And the `github-pages` environment that turning it on creates allows
deployments from the default branch only, while the release runs from a tag.
The job is then rejected before its first step: two seconds, no steps, no log
to say why. Once per repository:

```sh
gh api repos/<owner>/<repo>/environments/github-pages/deployment-branch-policies \
  -X POST -f name='v*' -f type=tag
```

To build one locally without releasing it:

```sh
uv run tools/make-release.py
```

It packs `dist/crossglyph-<version>.zip` from HEAD, and refuses to run against
a dirty working tree, since the archive comes from the commit rather than from
your files. Beside the zip it writes `dist/latest.json`, hashed from that very
file, which is what installs read to learn a newer release exists.

`git archive` does the reading; the tree is then repacked so the launcher, the
workspace and `update.conf` sit at the root and the code goes under
`versions/<version>/`. Members are copied as bytes rather than through the
filesystem, which is what keeps the wrappers exact.

The workspace files are the one thing that lands twice: at the root, which is
the copy the user edits, and inside the version, which is the record of how
they shipped. An update compares against that second copy to tell a file
somebody edited from one that changed between releases, and without it every
install would look edited.

### The launcher updates itself, one launch late

The launcher lands twice for the same reason: the root copy is the one that
runs, and the one inside the version is what an update stages beside it. A
release can therefore fix the launcher of an install already out there, which
is the whole reason it is in the version at all.

It cannot be replaced during the run that installs it. Both cmd.exe and a
POSIX shell read a script as they execute it and resume at the byte offset
they had reached, so a file that changed length underneath them is read from
the middle of a word. Measured on both rather than assumed: on Windows a
mid-run replacement, by write or by rename, makes cmd execute fragments like
`'ause'`; on Linux dash re-ran two lines and then failed. So the updater
writes `crossglyph.cmd.staged` and never touches the live file.

Two rules follow, and both are checked by `tests/test_shim.py`:

- **The apply must be one line ending in `exit /B`.** Anything after it, even
  a `)` closing a block cmd has to skip, is a read from the replaced file. The
  cost is that this one run reports exit 0 whatever the tool returned;
  `crossglyph.sh` uses `exec` and has no such trouble.
- **An old launcher must be able to start a new version.** It is one launch
  behind for exactly one launch, so keep it thin: read `current`, run the
  version it names. Anything that might need fixing belongs in the versioned
  tree, where a release replaces it outright.

The script then reads the archive back and checks that everything a release
needs is in it, that no checkout furniture or state file came along, that the
executable files still are, that every entry carries a Unix mode a POSIX
`unzip` will apply, and that `tools/uv.cmd` still has its mixed line endings.
A release that lost one of those unpacks cleanly, runs nowhere, and says
nothing about why. The mode check is there because losing it is silent on
Windows and total on Linux: an entry that keeps 0755 but does not say Unix
extracts unrunnable.

`.gitattributes`, `.gitignore`, `.githooks/` and `.github/` carry
`export-ignore`, so they stay out of the archive. They mean nothing to
somebody unpacking a zip.

## Rebuilding the render core

`src/crossglyph/render/render.wasm` is committed, because a release has no
toolchain to build one with. Rebuild it after pulling the firmware, and after
editing anything under `src/render/`.

### Where it is built from

The engine has a firmware checkout of its own, `crosspoint-reader-engine`
beside this repository, tracking `develop`. Nothing works in it. A checkout
you build firmware and run the emulator from moves between branches for
reasons that have nothing to do with the preview, and every one of those moves
would otherwise change what the core is built from and make the staleness
warning fire.

```sh
uv run tools/update-engine.py            # clone it, or fetch and fast-forward
uv run tools/update-engine.py --dry-run  # ask, change nothing
uv run tools/update-engine.py --ref v1.2 # a one-off, detached
```

It reports which commits since the stamp touch anything the build compiles,
sources and include directories both, so "has the renderer moved" is one
command rather than a reading of the firmware log. It never builds: that needs
emsdk, and on Windows a shell this is not.

The build resolves the firmware in one order, and `render/stamp.py` resolves
the same one so that what the module is built from and what it is judged
against cannot drift:

```
$CROSSGLYPH_FIRMWARE  ->  ../crosspoint-reader-engine  ->  ../crosspoint-reader
```

The last of those keeps a single-checkout setup working, which is what a
contributor and CI have. The first is how a build from a fork of the firmware
works, without anything here knowing that forks exist. `$FW` overrides the lot
for the build alone.

### Building it

It needs [emsdk](https://emscripten.org/docs/getting_started/downloads.html)
beside this repository, or `$EMSDK` naming it somewhere else.

```sh
bash src/render/build.sh
```

On Windows the script wants a MSYS2 bash:

```sh
c:/tools/msys64/usr/bin/env.exe MSYSTEM=MINGW64 \
  c:/tools/msys64/usr/bin/bash.exe -lc 'bash <repo>/src/render/build.sh'
```

Two things there are easy to get wrong and hard to diagnose. The C++ goes
through `em++` and the C through `emcc`, because each rejects the other's
sources. And a stub HAL must not have a data member: `HalDisplay` keeps its
framebuffer in a function local static because as a member of an `inline`
variable it came out null in one translation unit and valid in another, so
every drawn pixel vanished in silence.

The stubs under `src/render/hal/` stand in for the firmware's own HAL, so
their signatures have to track it. When the firmware changes one, the build
says so as a compile error naming both, which is the good case: an argument
added to `displayGrayBuffer` upstream stops the build rather than the page.

The build writes a stamp beside the module: the commit, the repository it came
from and the branch it was on. A checkout whose firmware has moved past that
commit gets a warning, once per run, and the preview draws with the older
renderer until you rebuild. A release has no firmware checkout, so nothing is
compared and nothing is said.

The repository name is in the stamp because the directory it was built from is
not the answer: an engine checkout is named for its job, and a second firmware
would be a second name. `crossglyph --version` reports what the stamp says.

## Writing

Comments explain why, not what. They describe what the code does now, never
what it used to do: git has that, and a comment retelling it is wrong by the
next change. A firmware behaviour a value works around is worth a citation, and
those citations are why several comments here are long.
