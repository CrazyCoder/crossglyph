# Command line

The browser is the normal way to tune and build a font. Use commands for batch
builds, scripts, custom workspaces or a preview server that runs in the
background.

Examples on this page use `crossglyph`. In an unpacked release, replace it with:

- `crossglyph.cmd` on Windows;
- `./crossglyph.sh` on macOS and Linux.

Run `crossglyph <command> --help` for the options in your installed version.

## Commands

| Command | Purpose |
|---|---|
| `preview` | Open the browser preview. This is the default command. |
| `start` | Start the preview in the background. |
| `stop` | Stop a preview. |
| `status` | Show the running preview and its version. |
| `restart` | Restart the background preview. |
| `build` | Build `.cpfont` families. |
| `fetch-fallbacks` | Download bundled fallback faces. |
| `update` | Install the latest release. |
| `update --check` | Check for a release. |
| `update --rollback` | Select the previous installed release. |

## Preview

Open the first family in the workspace:

```sh
crossglyph preview
```

With no command, CrossGlyph does the same thing:

```sh
crossglyph
```

Open a family by name:

```sh
crossglyph preview --family notosans
```

Open one regular font file outside a discovered family:

```sh
crossglyph preview --font one.ttf
```

Use `--bold`, `--italic` and `--bold-italic` to supply the other styles with
`--font`.

Common options:

| Option | Purpose |
|---|---|
| `--family NAME` | Open a discovered family. |
| `--font PATH` | Open one regular face. |
| `--bold PATH` | Supply a bold face. |
| `--italic PATH` | Supply an italic face. |
| `--bold-italic PATH` | Supply a bold italic face. |
| `--fonts DIR` | Use another font workspace. |
| `--host ADDRESS` | Bind the preview server to another address. |
| `--port PORT` | Use another port. |
| `--no-open` | Start the server without opening a browser. |

### Write one PNG

Use `--png` to render one page and exit:

```sh
crossglyph preview --family notosans --size 13 --png page.png
```

`--size` sets the point size. The optional `--device` flag selects one of the
render geometries included in the current release. Run
`crossglyph preview --help` for the available values.

## Background preview

Start the preview without keeping a terminal window open:

```sh
crossglyph start
```

Check it, restart it or stop it:

```sh
crossglyph status
crossglyph restart
crossglyph stop
```

`start` and `restart` accept preview options. This starts a family on another
port without opening a browser:

```sh
crossglyph start --family notosans --port 8123 --no-open
```

`status` reports the address, process, CrossGlyph version, workspace and log.
Use `--host` or `--port` with `status` and `stop` to name a particular preview:

```sh
crossglyph status --port 8123
crossglyph stop --port 8123
```

The background commands are unavailable inside a container. Start the preview
in the foreground and let Docker or Compose manage the process.

## Build fonts

Build every family that changed:

```sh
crossglyph build
```

Build one family:

```sh
crossglyph build notosans
```

The name may be a family name or config filename. Several names may be given in
one command.

| Option | Purpose |
|---|---|
| `--fonts DIR` | Use another font workspace. |
| `-o DIR`, `--out DIR` | Write to another output folder. |
| `-j N`, `--jobs N` | Rasterize this many point sizes in parallel. |
| `--force` | Rebuild every selected size. |
| `--list` | Show resolved families and settings without building. |
| `--fail-on-warning` | Return exit status 1 after a build that produced a warning. |

A normal build skips point sizes whose source files and settings match the last
build. `--force` ignores that record.

`--fail-on-warning` does not cancel output. It changes the exit status after
CrossGlyph writes the planned files.

### Use another workspace

```sh
crossglyph build --fonts D:/fonts-work --out D:/fonts-work/cpfonts
```

Pass both `--fonts` and `--out` when an isolated build must keep its output in
the same isolated folder. The default output is resolved from the normal
workspace before command options are read.

## Download bundled fallbacks

Download the bundled Noto faces into the workspace:

```sh
crossglyph fetch-fallbacks
```

The download includes the general fallback set. The large face used for
Chinese, Japanese and Korean is downloaded when a config requests that
coverage.

Use `--fonts DIR` to download into another workspace.

## Updates

Check now:

```sh
crossglyph update --check
```

Install the latest release:

```sh
crossglyph update
```

Select the previous retained release:

```sh
crossglyph update --rollback
```

Restart CrossGlyph after a command-line update or rollback. The browser's
**Update** button restarts a local preview itself.

See [Updating](updating.md) for automatic checks, retained files and privacy.

## Global options

Show the CrossGlyph and render-core versions:

```sh
crossglyph --version
```

Skip the automatic update check for one command:

```sh
crossglyph --no-update-check build
```

## Environment variables

| Variable | Purpose |
|---|---|
| `CROSSGLYPH_FONTS` | Default font workspace. |
| `CROSSGLYPH_OUT` | Default build output folder. |
| `CROSSGLYPH_HOST` | Default preview address. |
| `CROSSGLYPH_NO_UPDATE_CHECK` | Disable automatic update checks when present. |
| `CI` | Disable automatic update checks on build systems. |

Command options override environment defaults.

## Exit status

CrossGlyph returns 0 when a command succeeds. Invalid options, missing inputs
and refused operations return a nonzero status. A build with warnings returns 0
unless `--fail-on-warning` is set.

For font settings used by `build`, see [Font settings reference](fonts.md).
