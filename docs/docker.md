# Run CrossGlyph in Docker

Docker runs CrossGlyph without installing Python, uv or the project dependencies
on the host. The container can read and write one mounted workspace. That
folder holds the source fonts, configuration files, downloaded fallback faces
and built `.cpfont` families.

The preview has no authentication. The supplied Compose service publishes it
on `127.0.0.1` so that only the Docker host can open it.

## Start the preview

Run these commands from the CrossGlyph folder:

```sh
docker compose up -d --wait
```

Open <http://127.0.0.1:8000/>. Put TTF or OTF files in the local `fonts` folder.
The running preview finds workspace changes when the page regains focus.

Use these commands to read logs or stop the service:

```sh
docker compose logs -f
docker compose down
```

An installed release pulls the image tagged with that release's version. A
source checkout follows `latest`. To build the image from the current checkout,
add its build override:

```sh
docker compose -f compose.yaml -f compose.build.yaml \
  up -d --build --wait
```

## Run builds and other commands

The image entrypoint is `crossglyph`. A command after the Compose service name
replaces the default preview command while keeping the workspace mount and the
container restrictions.

```sh
docker compose run --rm crossglyph build
docker compose run --rm crossglyph build --force
docker compose run --rm crossglyph build notosans
docker compose run --rm crossglyph fetch-fallbacks
docker compose run --rm crossglyph --version
```

Docker owns the preview process lifetime. The native `start`, `stop`, `status`
and `restart` commands are unavailable in a container, so they cannot create
daemon state or detach a child process there. Use `docker compose up`,
`docker compose down` and `docker compose ps` instead.

Builds read source fonts from the workspace root and configs from `conf/`.
They write to `cpfonts/` unless `out` in `conf/all.conf` selects another path.
Use a path relative to the workspace so that the output remains in the mounted
folder.

The workspace has the same layout as a native CrossGlyph installation:

```text
fonts/
  MyFamily-Regular.ttf
  MyFamily-Bold.ttf
  conf/
    all.conf
    myfamily.conf
  fallbacks/
  cpfonts/
```

## Select another workspace or port

Compose reads the following environment variables. You can set them in the
shell or in a `.env` file beside `compose.yaml`.

| Variable | Default | Purpose |
|---|---|---|
| `CROSSGLYPH_WORKSPACE` | `./fonts` | The only host folder mounted into the container |
| `CROSSGLYPH_PORT` | `8000` | The host port for the preview |
| `CROSSGLYPH_BIND` | `127.0.0.1` | The host address that publishes the preview |
| `CROSSGLYPH_UID` | `1000` | The user ID that writes workspace files on Linux |
| `CROSSGLYPH_GID` | `1000` | The group ID that writes workspace files on Linux |
| `CROSSGLYPH_TAG` | Release version in an installed ZIP; `latest` in a checkout | The image tag to run |

On Linux, set `CROSSGLYPH_UID` and `CROSSGLYPH_GID` to the owner of the
workspace if that account does not use IDs 1000 and 1000. Docker Desktop
manages bind mount permissions on Windows and macOS.

## Run without Compose

Use an absolute host path with `docker run`. The image sets the preview host to
`0.0.0.0`, so both the default command and an explicit `preview` command accept
connections through the published port.

```sh
docker run --rm \
  --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  --mount type=bind,source=/absolute/path/to/fonts,target=/workspace \
  -p 127.0.0.1:8000:8000 \
  ghcr.io/crazycoder/crossglyph:latest
```

Replace the port option with a CLI command for a one-off build:

```sh
docker run --rm \
  --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  --mount type=bind,source=/absolute/path/to/fonts,target=/workspace \
  ghcr.io/crazycoder/crossglyph:latest build
```

## Update the image

An installed ZIP defaults to its own version so native and container launches
run the same code. Set `CROSSGLYPH_TAG` in `.env` to move a container-only
deployment to another version, or to `latest` to follow each release. Then pull
the selected image and recreate the service:

```sh
docker compose pull
docker compose up -d --wait
```

The workspace is outside the container, so this does not replace fonts,
configs, fallbacks or output.

A native `crossglyph update` replaces an untouched root `compose.yaml` with the
one pinned to the new release. If you edited that file, the update keeps it and
writes `compose.yaml.new` beside it. Put deployment settings in `.env` so the
managed Compose file can update without a conflict.

Published images support `linux/amd64` and `linux/arm64`. Each release also
carries build provenance and an SBOM in the GitHub Container Registry.

## Security boundary

The Compose service runs as a non-root user. Its application filesystem is
read-only, Linux capabilities are removed, and privilege escalation is
disabled. `/tmp` is temporary. `/workspace` is the only host path the service
can write.

CrossGlyph can change every file in the mounted workspace. Do not mount a
parent directory or a folder that contains unrelated files. The container does
not mount the Docker socket.

Do not publish the preview directly on `0.0.0.0`. The current server has no
login, and its save and build endpoints write to the workspace. Put an
authenticated TLS reverse proxy in front of CrossGlyph before making it
available on another machine.

The bind mount is the current input and output path. A future upload and
download interface can use the same `/workspace` contract with a Docker volume
instead of a host folder. That change does not require another image entrypoint
or another internal storage layout.
