# Updating

CrossGlyph looks for a newer release about once a day and tells you when there
is one. It installs nothing until you ask it to.

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
note: 0.2.0 is available. Run crossglyph update to install it.
```

The second sentence depends on how CrossGlyph was installed. A clone is told
to pull, a container to take the new image, an unpacked release to run the
command above. None of them is told anything while there is nothing to do: the
comparison is the version this install reports against the published one, so a
clone that is behind that release hears about it and one that is not is left
alone.

A source download is the exception, and says what it is whatever the check
found. Its version is whatever the last release set, so a tree taken from the
default branch after that reports the release and compares as up to date while
holding rather more than it did.

In the preview, the island under the specimen answers the question: the new
version when there is one, and **Up to date.** when there is not. When it last
looked is a fact about that answer rather than the answer itself, so it sits
on the line below with the rest of what this install is. Beside it is one
button: **Check now**
ordinarily, and **Update** in its place when there is a release this install
can install. The name at the left of that line links the project, and the
address comes from the same constant the updater fetches from, so the two
cannot come to point at different places.

Where that button can do the whole job, the line below says nothing about how
to update: a command beside a button that runs it is only noise. The kinds the
button cannot help still say what would, and so does a source download, whose
answer is not the command but what pressing it would do to the install.

## Asking on purpose

```sh
crossglyph update --check
```

Asks straight away, whatever the interval says and whether or not automatic
checks are turned off. It reports every answer, including the three the
automatic check keeps to itself: that you are up to date, that it could not
reach the server, and a release you rolled back from.

**Check now** in the preview does the same thing, and offers what it finds.

## Installing one

```sh
crossglyph update
```

The **Update** button in the preview does the same thing, with a bar for the
download.

It fetches the manifest, stops if there is nothing newer, downloads the
release, checks it against the SHA-256 the manifest gave, unpacks it into
`versions/<new version>`, and writes that version into `current`.

Nothing is replaced in place. The version you were on stays where it is, and
so does everything at the root: `update.conf`, your `fonts` folder, and the
launcher, which is dealt with below. What is installed does not become what is
running until you start CrossGlyph again.

The preview says so and stops offering the release, since it is already on the
disk. That comes from the disk rather than from the page that pressed the
button, so a reload, a second browser and an update run from the command line
while the preview is open are all told the same thing: a server that goes on
being the version it started as would otherwise find that release on every
check and offer it again.

An update interrupted anywhere leaves an install that still runs. The download
goes to `versions/.tmp-<version>.zip` and the unpack to
`versions/.incoming-<version>`, neither of which the launcher will ever start,
and both of which are swept at the next launch.

Installing a version whose directory is already there, which is what rolling
forward after a rollback does, moves the old one to `versions/.old-<version>`
rather than deleting it. That is not tidiness: the environment uv built inside
it shares its files with every other environment on the drive, and while
CrossGlyph is running those files cannot be deleted at all. The directory is
another name the launcher will never start, and it goes at the next launch.

One thing stops it before it downloads anything: an install that does not own
its own files, which is a clone, a container, or a folder nobody can write to.
The notice says what to do instead.

### The launcher

`crossglyph.cmd` and `crossglyph.sh` are the one thing an update cannot write
over, because one of them is the file running the update. Both cmd.exe and a
POSIX shell read a script as they execute it and resume at the offset they had
reached, so a file that changed length underneath them is read from the middle
of a word.

So a release that changes the launcher leaves the new one beside it, as
`crossglyph.sh.staged` or `crossglyph.cmd.staged`, and the launcher applies it
at the next launch before it does anything else. The one it replaces is kept
with `.previous` on the end: if a launcher ever ships broken, renaming that
back undoes it without reinstalling anything.

Nothing about this needs doing by hand, and nothing is left half applied: an
install whose launcher is one release behind still runs, because what the
launcher does is read `current` and start the version it names.

### Your workspace

An update never writes over a file you edited. For each file it ships into
`fonts`, today `README.md` and `conf/all.conf`:

- if it is not there, it is written;
- if it is exactly as it shipped, it is replaced, since you never touched it;
- otherwise yours is kept, the new one is written beside it as
  `<name>.new`, and the update says so.

Everything else in `fonts` is yours and is not looked at.

### A source download

A tree from the **Code** button on GitHub has no `versions` folder and no
`current`, so it runs where it stands. `crossglyph update` converts it: it
adds those two things and changes nothing else. The launcher already prefers
the versioned layout, so the next run starts the new version, and the install
updates normally from then on.

The files at the root are left where they are. They are no longer read, and
deleting a folder somebody unpacked themselves is a larger act than adding two
things to it. Delete them yourself if you want the disk back.

The offer only appears when the published release is newer than the version in
the tree. A snapshot taken from the default branch reports the version of the
last release while holding rather more than it did, so installing that release
over the top would be a step backwards.

## Going back

```sh
crossglyph update --rollback
```

Puts `current` back to the version before this one and says so. Restart
CrossGlyph and you are on it.

The version you left is recorded, and the checks CrossGlyph makes on its own
stay quiet about it until something newer than it appears. Otherwise the next
one would offer you the release you just escaped, and go on offering it every
day.

That silence is the tool not raising the subject, and it is nothing more than
that. Ask and you are answered: `crossglyph update --check` and **Check now**
both name that release and say why nothing had mentioned it, the button
appears beside it, and `crossglyph update` installs it. A rollback is a
decision about being nagged, not one you have to undo to change your mind.

## How many versions are kept

The one in use and one more, which is what rolling back needs. Older ones are
removed at the next launch, on a background thread in the preview, so a large
removal never delays the page. `keep_versions` in `update.conf` changes the
count.

A version costs about 3 MB unpacked, and about 80 MB once it has been run and
uv has built its environment. Nothing removes the version in use, the version
`current` names, or the one this process is running from, and a directory that
will not go is left for the next launch rather than failing anything.

## Settings

`update.conf` sits beside the launcher, at the top of the folder you unpacked.
It ships fully commented, so having it changes nothing until you edit a line.

| Key | Default | What it does |
|---|---|---|
| `check` | `yes` | Set to `no` to stop it asking on its own. |
| `interval_hours` | `24` | How long to wait between checks. |
| `keep_versions` | `1` | Versions kept besides the one in use. Zero keeps none, and leaves nothing to roll back to. |

A value that does not parse leaves the default rather than being guessed at.

## Turning it off

Any one of these stops the automatic check. They are not a precedence chain,
so one is enough and a `yes` in the config does not overrule the others:

- `check = no` in `update.conf`;
- the `CROSSGLYPH_NO_UPDATE_CHECK` environment variable, set to anything;
- `--no-update-check` on any command, for that run only;
- the `CI` environment variable, which is set for you on build machines.

None of them touches `crossglyph update --check`, `crossglyph update` or the
two buttons. Those are you asking, which is a different thing from the tool
asking. Nothing installs itself either way.

## What it writes

`.update-state.json`, beside the launcher: when it last looked, what it found,
and the version a rollback rejected. Deleting it costs one more check, and
un-rejects a version you rolled back from.

## What it sends

A plain HTTPS GET for `latest.json`, and, when you ask for an update, a GET
for the release zip. No identifier, no version, no count. The server learns
what any web server learns from a request, and CrossGlyph tells it nothing
further.
