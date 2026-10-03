// --- pixel zoom -------------------------------------------------------------
// The device page enlarged until each of the reader's pixels is a block you
// can see, with a grid between them, the way a photo editor shows an image
// close up. Every block is a whole number of screen pixels: a block of 10 and
// one of 11 side by side would make the grid lie about which strokes are as
// wide as each other.
//
// What follows is arithmetic on plain numbers, so it can be checked without a
// canvas. A state is {level, x, y}: the level in percent, 0 for off, and the
// centre of the view in reader pixels.

//: The levels on offer, in percent of 1:1 pixels.
export const LEVELS = [200, 400, 800, 1000, 1600, 2400, 3200];
//: Below this a block is too small for a line to leave the pixel readable.
export const GRID_FROM = 400;
//: What a double-click zooms to before any level has been chosen.
export const FIRST_LEVEL = 1000;
//: How far a press moves, in CSS pixels, before it is a pan.
export const DRAG_PX = 3;
//: How long a press stays still before it is the untuned hold.
export const HOLD_MS = 300;
//: A light grey that none of the reader's four levels lands on once toned at
//: the default paper and ink.
export const GRID_RGB = [190, 190, 190];

export function stepLevel(level, direction) {
  const at = LEVELS.indexOf(level);
  if (direction > 0) return LEVELS[Math.min(at + 1, LEVELS.length - 1)];
  return at <= 0 ? 0 : LEVELS[at - 1];
}

// Screen pixels per reader pixel, rounded so every block is the same size.
// At 1.25x, 1000% asks for 12.5 and gets 13.
export function blockSize(level, dpr) {
  return Math.max(1, Math.round(level / 100 * dpr));
}

// One axis of the view's offset into the zoomed page, in screen pixels. A
// page smaller than the view is centred; otherwise the view stops at its
// edges rather than showing past them.
function offsetOn(centre, extent, panelExtent, block) {
  const full = panelExtent * block;
  if (full <= extent) return Math.round((full - extent) / 2);
  return Math.min(Math.max(Math.round(centre * block - extent / 2), 0),
                  full - extent);
}

export function origin(state, view, panel, block) {
  return {x: offsetOn(state.x, view.width, panel.width, block),
          y: offsetOn(state.y, view.height, panel.height, block)};
}

// The centre the view really has once it is kept on the page, so a pan that
// ran into an edge leaves nothing to pay back before it moves again.
export function clampCentre(state, view, panel, block) {
  const at = origin(state, view, panel, block);
  return {...state, x: (at.x + view.width / 2) / block,
          y: (at.y + view.height / 2) / block};
}

// The centre kept on the panel, for a state read back from storage or carried
// over to a reader of another size.
export function inside(state, panel) {
  return {...state, x: Math.min(Math.max(state.x, 0), panel.width),
          y: Math.min(Math.max(state.y, 0), panel.height)};
}

// A drag moves the page with the pointer, so the centre goes the other way.
export function panBy(state, dx, dy, block) {
  return {...state, x: state.x - dx / block, y: state.y - dy / block};
}

// The state at `level` that puts `reader` (a point in reader pixels) under
// `point` (screen pixels from the view's top left corner).
export function zoomAt(level, reader, point, view, dpr) {
  const block = blockSize(level, dpr);
  return {level, x: reader.x + (view.width / 2 - point.x) / block,
          y: reader.y + (view.height / 2 - point.y) / block};
}

// Where in the page a point of the view falls, in reader pixels. Unzoomed,
// the view is the whole page.
export function readerAt(state, point, view, panel, dpr) {
  if (!state.level) {
    return {x: point.x * panel.width / view.width,
            y: point.y * panel.height / view.height};
  }
  const block = blockSize(state.level, dpr);
  const at = origin(state, view, panel, block);
  return {x: (at.x + point.x) / block, y: (at.y + point.y) / block};
}

// The reader pixels a view touches, whole ones only and none past the page:
// what a copy of the zoomed view holds.
export function visibleCrop(at, view, panel, block) {
  const left = Math.max(0, Math.floor(at.x / block));
  const top = Math.max(0, Math.floor(at.y / block));
  const right = Math.min(panel.width, Math.ceil((at.x + view.width) / block));
  const bottom = Math.min(panel.height, Math.ceil((at.y + view.height) / block));
  return {left, top, width: right - left, height: bottom - top};
}

const within = (value, block) => ((value % block) + block) % block;

// Fill `out`, an RGBA array of `view` size, with the page enlarged by `block`
// from offset `at`. Nearest neighbour and nothing else: a block is its reader
// pixel exactly. A grid line takes the last row and column of each block, so
// it narrows a pixel without hiding one. Past the page is `outside`.
export function paint(source, panel, at, block, grid, view, outside, out) {
  for (let y = 0; y < view.height; ++y) {
    const down = at.y + y;
    const row = Math.floor(down / block);
    const rowLine = grid && within(down, block) === block - 1;
    const off = row < 0 || row >= panel.height;
    for (let x = 0; x < view.width; ++x) {
      const across = at.x + x;
      const column = Math.floor(across / block);
      const to = (y * view.width + x) * 4;
      out[to + 3] = 255;
      if (off || column < 0 || column >= panel.width) {
        out[to] = outside[0];
        out[to + 1] = outside[1];
        out[to + 2] = outside[2];
      } else if (rowLine || (grid && within(across, block) === block - 1)) {
        out[to] = GRID_RGB[0];
        out[to + 1] = GRID_RGB[1];
        out[to + 2] = GRID_RGB[2];
      } else {
        const from = (row * panel.width + column) * 4;
        out[to] = source[from];
        out[to + 1] = source[from + 1];
        out[to + 2] = source[from + 2];
      }
    }
  }
  return out;
}
