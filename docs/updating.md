# Updating

CrossGlyph checks for a newer release about once a day. The check only reports
what is available. An update starts when you press **Update** or run the update
command.

## Check in the browser

The status below the sample text shows one of these results:

- **Up to date**
- a newer release is available
- the check is off
- the release server could not be reached

Press **Check now** to check immediately. This works even when automatic checks
are off.

Automatic checks run in the background. They do not delay a preview render or a
font build.

## Install an update

When a newer release is available, **Check now** becomes **Update**.

Press **Update** to:

1. download the release;
2. verify its SHA-256 checksum;
3. install it beside the current version;
4. restart the local preview;
5. reload the browser page.

The page may lose its connection while the preview restarts. It waits for the
new process and reloads after the server answers.

A container, source checkout or read-only installation may require another
update method. The status line tells you what to do for that installation.

## Files kept during an update

Updates keep the font workspace and its settings. This includes:

- source fonts;
- family config files;
- built `.cpfont` files;
- downloaded fallback faces;
- `update.conf`.

CrossGlyph also protects editable templates and Docker configuration. If you
changed a shipped file, the update places the new copy beside it with a `.new`
suffix.

## Roll back

Rollback is a command-line operation. It selects the previous retained release.
See [Updates on the command line](cli.md#updates).

After a rollback, automatic checks do not offer the release you left. A newer
release will appear normally. **Check now** still reports the release you left
and explains why the automatic check did not offer it.

## Automatic check settings

`update.conf` is beside the launcher. These keys control automatic checks:

| Key | Default | Meaning |
|---|---|---|
| `check` | `yes` | Set to `no` to disable automatic checks. |
| `interval_hours` | `24` | Hours between checks. |
| `keep_versions` | `1` | Installed versions kept beside the active version. |

Example:

```ini
check = no
```

Turning off automatic checks does not disable **Check now**, **Update** or the
matching commands. Those actions start only when you request them.

Environment variables and the one-command option are listed in
[Command line](cli.md#global-options).

## Network requests

An automatic check sends one HTTPS request for `latest.json`. The file contains
the newest release number and download information.

The request does not include an installation ID, the installed CrossGlyph
version or a usage count. Installing an update adds one request for the release
archive.

CrossGlyph stores the last check result in `.update-state.json` beside the
launcher. Deleting that file resets the recorded check time and rollback choice.
