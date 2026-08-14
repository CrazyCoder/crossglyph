# Updating

CrossGlyph looks for a newer release about once a day and tells you when there
is one. It does not download or install anything.

## What it does, and when

The check reads one small file on the web, `latest.json`, which says what the
newest release is. It compares that with the version you are running and says
something only when the release is newer.

It never runs while you are waiting for anything:

- the command line checks **after** the work is done, so a build is never
  slower for it;
- the preview checks on a background thread while it starts, so the page is
  never later for it.

Either way it gives up after two seconds, and it asks at most once per
interval. An install with no network costs one two second wait a day and says
nothing.

## What you see

On the command line, after `crossglyph build` or `crossglyph fetch-fallbacks`,
one line:

```
note: 0.2.0 is available. Download the new release to update.
```

The second sentence depends on how CrossGlyph was installed. A clone is told
to pull, a container to take the new image, an unpacked release to download
the next one.

In the preview, a dot appears beside the version at the top of the left panel,
and the block at the foot of the export panel names the new version. That
block also says when it last looked, with a **Check now** button beside it.

## Asking on purpose

```sh
crossglyph update --check
```

Asks straight away, whatever the interval says and whether or not automatic
checks are turned off. It reports all three answers, including the two the
automatic check keeps to itself: that you are up to date, and that it could
not reach the server.

**Check now** in the preview does the same thing.

## Settings

`update.conf` sits beside the launcher, at the top of the folder you unpacked.
It ships fully commented, so having it changes nothing until you edit a line.

| Key | Default | What it does |
|---|---|---|
| `check` | `yes` | Set to `no` to stop it asking on its own. |
| `interval_hours` | `24` | How long to wait between checks. |

A value that does not parse leaves the default rather than being guessed at.

## Turning it off

Any one of these stops the automatic check. They are not a precedence chain,
so one is enough and a `yes` in the config does not overrule the others:

- `check = no` in `update.conf`;
- the `CROSSGLYPH_NO_UPDATE_CHECK` environment variable, set to anything;
- `--no-update-check` on any command, for that run only;
- the `CI` environment variable, which is set for you on build machines.

None of them touches `crossglyph update --check` or the **Check now** button.
Those are you asking, which is a different thing from the tool asking.

## What it writes

`.update-state.json`, beside the launcher: when it last looked and what it
found. Deleting it costs nothing but one more check.

## What it sends

A plain HTTPS GET for `latest.json` and nothing else. No identifier, no
version, no count. The server learns what any web server learns from a
request, and CrossGlyph tells it nothing further.
