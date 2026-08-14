"""Load and drive the firmware's render core, compiled to WebAssembly.

The device's own EpdFont and GfxRenderer, built by src/render/build.sh into a
freestanding module -- bytes in, bytes out, no syscalls. That is what makes the
preview honest: it is not a reimplementation of the renderer, it is the
renderer. It is also what lets the same .wasm load in a browser later, with
only this wrapper replaced.

The module ships with the package and records the firmware commit it was built
from, so a release runs with no toolchain and no firmware clone. See
docs/preview.md.
"""
from __future__ import annotations

import contextlib
import functools
import pathlib
import sys
import threading
from collections.abc import Iterator

from . import stamp
# Spelled as this module's own before the split, and every caller still spells
# them that way. The module is imported too, because a test that redirects a
# path has to reach the code that reads it.
from .stamp import (FIRMWARE, ROOT, STAMP_PATH, WASM_PATH, build_stamp,
                    firmware_commit, is_stale)


class RenderCoreMissing(RuntimeError):
    """There is no .wasm to load. Being out of date is a warning, not this."""


# libc links stdio unconditionally, so a module that never prints still imports
# these three. They are standard WASI, satisfied natively here and by any
# off-the-shelf shim in a browser -- unlike Emscripten's own
# env.emscripten_notify_memory_growth, which -sPURE_WASI keeps out of the build.
# Pinned rather than merely tolerated: a *new* import is a regression worth
# failing on.
EXPECTED_IMPORTS = frozenset({
    "wasi_snapshot_preview1.fd_close",
    "wasi_snapshot_preview1.fd_seek",
    "wasi_snapshot_preview1.fd_write",
})


class RenderModule:
    """One instantiation of the render core, with its own linear memory."""

    def __init__(self, path: pathlib.Path):
        # Imported here rather than at the top, so that reading what the core
        # says about itself does not load a wasm runtime to do it. `crossglyph
        # --version` wants the firmware commit and nothing else. Same reason
        # cli.py defers the preview: a command should not pay for what it
        # never touches.
        import wasmtime

        engine = wasmtime.Engine()
        self._store = wasmtime.Store(engine)
        # The module imports WASI stdio it never calls; wasmtime supplies it.
        self._store.set_wasi(wasmtime.WasiConfig())
        linker = wasmtime.Linker(engine)
        linker.define_wasi()
        module = wasmtime.Module.from_file(engine, str(path))
        self._instance = linker.instantiate(self._store, module)
        self._exports = self._instance.exports(self._store)
        self._memory = self._exports["memory"]
        #: Pointers handed out by write()/alloc(), freed by release().
        self._owned: list[int] = []

    def call(self, name: str, *args):
        export = self._exports.get(name)
        if export is None:
            raise AttributeError(f"the render core exports no {name!r}")
        return export(self._store, *args)

    def write(self, data: bytes) -> int:
        """Copy bytes into module memory, returning the pointer."""
        pointer = self.call("malloc", len(data))
        self._memory.write(self._store, data, pointer)
        self._owned.append(pointer)
        return pointer

    def alloc(self, size: int) -> int:
        """Reserve module memory for the core to write into."""
        pointer = self.call("malloc", size)
        self._owned.append(pointer)
        return pointer

    def release(self) -> None:
        """Free everything written since the last release.

        The core *borrows* what it is handed -- rc_font_load keeps a pointer to
        the .cpfont bytes for the life of the font, and rc_page_render reads
        the text again on each of its three passes -- so nothing can be freed
        while an operation is running. This runs at the start of the next one
        instead, where the previous render is provably finished with them.

        Without it a long-lived server leaks a font per render: measured at
        ~195 KB a time on a four-face family, which is 22 MB over 200 knob
        turns and does not stop.
        """
        if not self._owned:
            return
        # Drop the font first. rc_font_load keeps rc::g_data pointing at the
        # .cpfont bytes about to be freed, and exclusive() is a public entry
        # point: without this, a caller that measures before it draws --
        # rc_probe_text_width, rc_font_advance_y -- would read a heap block
        # malloc has already handed on. A null image makes the load fail,
        # which clears g_loaded, so those return 0 instead of nonsense.
        self.call("rc_font_load", 0, 0)
        for pointer in self._owned:
            self.call("free", pointer)
        self._owned.clear()

    def read(self, pointer: int, length: int) -> bytes:
        return bytes(self._memory.read(self._store, pointer, pointer + length))


@functools.lru_cache(maxsize=1)
def shared_module() -> RenderModule:
    """One instance for a process, so state set on it survives to the render.

    The core keeps the loaded font, the layout options and the framebuffer in
    module globals -- that is what makes it cheap, and it means a spec set on
    one instance and a page drawn by another would silently drop every knob.
    Callers that want isolation build their own with load_module().

    Take `exclusive()` rather than calling this directly from anything that
    might run on more than one thread.
    """
    return load_module()


#: Reentrant because an operation nests: preview_page holds it across the spec
#: it sets *and* the render that reads it.
_LOCK = threading.RLock()

#: How deep the nesting is, so the buffers of the last operation are freed once
#: at the top rather than under a caller still using them. Guarded by _LOCK.
_depth = 0


@contextlib.contextmanager
def exclusive() -> Iterator[RenderModule]:
    """The shared core, held for a whole operation.

    Two reasons, either of which is sufficient. A wasmtime Store must not be
    entered from two threads at once: doing so panics inside wasmtime's stack
    walker and takes the process with it, which is what a server threadpool
    does the moment two renders overlap. And the core keeps the font, the page
    spec and the framebuffer in module globals, so even a tolerant runtime
    would let two renders interleave into one framebuffer and hand each caller
    a page built from both.

    So the unit that has to be exclusive is the whole operation -- set the
    spec, load the font, run the passes, read the result -- not the individual
    calls.

    Entering the outermost one also frees the previous operation's buffers; see
    RenderModule.release for why that happens here rather than on the way out.
    """
    global _depth
    with _LOCK:
        module = shared_module()
        if _depth == 0:
            module.release()
        _depth += 1
        try:
            yield module
        finally:
            _depth -= 1


def _rebuild_hint() -> str:
    return f"  bash {ROOT / 'src' / 'render' / 'build.sh'}"


#: Said once per process. A page redraws on every knob turn, and a warning
#: repeated a hundred times is one nobody reads.
_said_stale = False


def load_module(path: pathlib.Path | None = None) -> RenderModule:
    """The render core, with a word about it if the firmware has moved on.

    A module built from an older firmware still draws the page the older
    firmware drew, which is worth more than no preview at all. It is worth
    saying so, though: whoever moved the checkout is the one person who can
    rebuild it. Passing an explicit path skips the check, since a caller naming
    a file has already said which one they mean.
    """
    global _said_stale
    if path is not None:
        if not path.is_file():
            raise RenderCoreMissing(
                f"{path} not found. Build it with:\n{_rebuild_hint()}")
        return RenderModule(path)

    if not stamp.WASM_PATH.is_file():
        raise RenderCoreMissing(
            f"{stamp.WASM_PATH} not found. Build it with:\n{_rebuild_hint()}")
    if stamp.is_stale() and not _said_stale:
        _said_stale = True
        current, where = stamp.current_firmware()
        print(f"warning: the render core was built from {stamp.describe()}, "
              f"and {where} is now at {stamp.short(current)}.\n"
              f"         The preview draws with the older renderer until you "
              f"rebuild it:\n{_rebuild_hint()}", file=sys.stderr)
    return RenderModule(stamp.WASM_PATH)


def module_imports(path: pathlib.Path | None = None) -> set[str]:
    """Host functions the module needs. Empty means genuinely freestanding.

    This is the property the browser phase rests on, so it is asserted in the
    tests rather than merely intended.
    """
    import wasmtime

    path = path or stamp.WASM_PATH
    engine = wasmtime.Engine()
    module = wasmtime.Module.from_file(engine, str(path))
    return {f"{item.module}.{item.name}" for item in module.imports}
