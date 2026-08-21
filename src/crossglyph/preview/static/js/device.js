import {numberOf, pairSlider, setNumeric, showSlider, wireStepper} from "./knobs.js";
import {attempt} from "./remember.js";

export const DEVICE_STORE = "crossglyph.device";

export const surface = document.getElementById("device-surface");
export const canvas = document.getElementById("device-page");
const frame = document.getElementById("device-frame");
const model = document.getElementById("device-model");
const color = document.getElementById("device-color");
const frameShown = document.getElementById("device-frame-shown");
const scale = document.getElementById("device-scale");
const paper = document.getElementById("device-paper");
const paperSlider = document.getElementById("device-paper-slider");
const ink = document.getElementById("device-ink");
const inkSlider = document.getElementById("device-ink-slider");
const warm = document.getElementById("device-warm");
const warmSlider = document.getElementById("device-warm-slider");
const tint = document.getElementById("device-tint");
const tintSlider = document.getElementById("device-tint-slider");
const tintFuncs = ["r", "g", "b"].map(
  channel => document.getElementById(`frame-tint-${channel}`));
const calibration = document.getElementById("device-calibration");
const calibrationRange = document.getElementById("device-calibration-range");
const calibrationSlider = document.getElementById("device-calibration-slider");
const ruler = document.getElementById("device-ruler");
const reset = document.getElementById("reset-device");
const copyButton = document.getElementById("device-copy");

const root = document.documentElement;


function syncPreviewColumns() {
  // Ask the actual grid. Reader model, frame, scale, DPR and viewport height
  // all change its intrinsic width, so a fixed viewport breakpoint cannot.
  // Read the viewport after trying two columns: stacking may add a vertical
  // scrollbar, and its narrower width must not prevent expansion restoring.
  root.dataset.previewColumns = "two";
  const available = Number(root?.clientWidth);
  if (!available) return;
  root.dataset.previewColumns =
    Number(root.scrollWidth) > available ? "one" : "two";
}

// Geometry in each frame PNG's own pixels, emitted by fb2xt's frame renderer
// from the same run that produced the pixels, so the two cannot disagree.
//
// The aperture is not the screen hole. It is the smallest rectangle carrying
// the panel's exact proportions that still contains that hole, centred on it,
// and it is what the page is drawn into. Two reasons. The page overlaps the
// hole's anti-aliased rim instead of stopping at it, which is what keeps a dark
// line from appearing down each side. And every scale applies one factor to
// both axes, so an aperture of any other shape lands the page on fractional
// device pixels: the glass is 0.60304 against the panel's 0.6, which put 800
// source rows into 796. The overhang tucks under the frame, which draws above.
//
// Each device is rendered twice and the two are not interchangeable. In
// `pixels` the aperture is the panel itself, so the factor 1:1 works out --
// native.width / aperture.width -- comes to one and the frame draws at its own
// pixels whatever the device pixel ratio. `scaled` is for every other mode: fit
// caps the frame at 480 CSS px, which at a 3x ratio wants 1440 device pixels
// and would upscale the smaller frame by more than two.
//
// Both are rendered rather than resampled from each other, so the smaller one
// keeps its edges and its buttons: measured at the size 1:1 shows it, its chin
// contrast is within a few levels of downsampling the tall one.
export const DEVICES = {
  x4: {
    native: {width: 480, height: 800},
    scaled: {
      frame: {width: 1118, height: 1820},
      aperture: {x: 117, y: 100, width: 873, height: 1455, radius: 16},
      body: {x: 8, y: 8, width: 1091, height: 1804,
             widthMm: 69.15, heightMm: 114.31},
    },
    pixels: {
      frame: {width: 612, height: 996},
      aperture: {x: 63, y: 53, width: 480, height: 800, radius: 9},
      body: {x: 4, y: 4, width: 598, height: 988,
             widthMm: 69.15, heightMm: 114.31},
    },
  },
  x3: {
    native: {width: 528, height: 792},
    scaled: {
      frame: {width: 1209, height: 1820},
      aperture: {x: 130, y: 122, width: 948, height: 1422, radius: 16},
      body: {x: 19, y: 19, width: 1171, height: 1793,
             widthMm: 63.74, heightMm: 97.59},
    },
    pixels: {
      frame: {width: 671, height: 1011},
      aperture: {x: 72, y: 67, width: 528, height: 792, radius: 9},
      body: {x: 10, y: 10, width: 651, height: 997,
             widthMm: 63.74, heightMm: 97.59},
    },
  },
};

const CSS_PIXELS_PER_MM = 96 / 25.4;
// XTEINK's accurate white X4 front photograph measures the display at
// 51, 105, 160 and 215. The black product photograph darkens the display and
// is only a reference for its frame.
const LEVELS = [0, 96, 200, 255];
const LEVEL_RATIOS = [0, .329, .665, 1];

// What each render calls its file. The tall one keeps the plain name, being the
// one every mode but 1:1 draws.
const SUFFIX = {scaled: "", pixels: "-1to1"};

// Which of the two renders this scale wants. Read live rather than stored, so
// changing the scale swaps the frame, its geometry and its file together and
// they cannot disagree about which one is on screen.
function variant() {
  return scale.value === "pixels" ? "pixels" : "scaled";
}

// One device's geometry, with the panel size the two renders share. Takes the
// variant so the copy can ask for `pixels` while the page is showing the other.
function profile(which = variant()) {
  const device = DEVICES[model.value] || DEVICES.x4;
  return {native: device.native, ...device[which]};
}

function dpr() {
  return Number(globalThis.devicePixelRatio) || 1;
}

function frameUrl(which = variant()) {
  return `device/${model.value}-${color.value}${SUFFIX[which]}.png`;
}

let fixedColor = false;

function themeColor() {
  return document.documentElement.classList.contains("dark") ? "black" : "white";
}

export function syncDeviceColor() {
  if (fixedColor) return;
  color.value = themeColor();
  layoutDevice();
}

function fitFactor(device, shown) {
  const width = shown ? device.frame.width : device.aperture.width;
  const height = shown ? device.frame.height : device.aperture.height;
  const viewportWidth = Number(globalThis.innerWidth) || 1200;
  const viewportHeight = Number(globalThis.innerHeight) || 900;
  return Math.max(.1, Math.min(480 / width, (viewportWidth - 56) / width,
                               viewportHeight * .72 / height));
}

function sourceFactor(device, shown) {
  if (scale.value === "pixels") {
    return device.native.width / device.aperture.width / dpr();
  }
  if (scale.value === "device" || scale.value === "custom") {
    const correction = scale.value === "custom"
      ? Number(calibrationRange.value) / 100 : 1;
    return CSS_PIXELS_PER_MM * correction * device.body.heightMm /
      device.body.height;
  }
  return fitFactor(device, shown);
}

// Nudge the page onto whole device pixels. Through `left` and `top` rather
// than a transform, and the difference is the whole point: a transform is
// applied exactly, so the canvas rasterizes at the fraction it carries, and
// `image-rendering: pixelated` settles that by nearest neighbour. Half a device
// pixel is the tie in that rounding, and the page comes out with stems a pixel
// wide in one place and two in the next. A relative offset is snapped to whole
// device pixels when it paints, so the same fraction costs nothing.
//
// Only one case ever asks for half a pixel, which is why this is easy to miss:
// the stage centres the surface, and the X3 frame is odd on both axes where the
// X4 frame is even, so an X3 with its frame shown is the one that lands between
// pixels. Every other reader, and every reader with the frame off, is already
// aligned and reaches this with nothing to correct.
//
// getBoundingClientRect() reports where a transform put the element, so it
// calls both spellings aligned and cannot tell them apart. What tells them
// apart is a screenshot compared against the canvas's own bitmap.
//
// The size needs no such care, which is worth saying because it looks as
// though it should. A CSS length is a multiple of a sixty-fourth of a pixel,
// so asking for the panel over the ratio can miss by half of that, and the
// box comes out a fraction of a device pixel off the bitmap it holds. That
// fraction is the whole drift from one edge to the other, so the furthest any
// column moves is the ratio over 128, well under a hundredth of a pixel, and
// nearest neighbour does not move a column until half of one. Measured at
// ratios where the panel is not expressible at all, every pixel still lands
// where the bitmap put it.
function alignPixelGrid() {
  if (scale.value !== "pixels" ||
      typeof canvas.getBoundingClientRect !== "function") return;
  const rect = canvas.getBoundingClientRect();
  const ratio = dpr();
  surface.style.left =
    `${(Math.round(rect.left * ratio) - rect.left * ratio) / ratio}px`;
  surface.style.top =
    `${(Math.round(rect.top * ratio) - rect.top * ratio) / ratio}px`;
}

export function layoutDevice() {
  const device = profile();
  const shown = frameShown.checked;
  const factor = sourceFactor(device, shown);
  const box = shown ? device.frame : device.aperture;

  surface.style.width = `${box.width * factor}px`;
  surface.style.height = `${box.height * factor}px`;
  canvas.style.left = `${shown ? device.aperture.x * factor : 0}px`;
  canvas.style.top = `${shown ? device.aperture.y * factor : 0}px`;
  canvas.style.width = `${device.aperture.width * factor}px`;
  canvas.style.height = `${device.aperture.height * factor}px`;
  canvas.style.borderRadius = `${device.aperture.radius * factor}px`;
  // The canvas holds real pixels of this screen, so a new size is a new
  // picture. Here rather than left to the caller: every route that changes the
  // size comes through here, and one that forgot the redraw would leave the
  // page at the last size, stretched by the browser to fit the new one.
  drawDevicePage();
  frame.hidden = !shown;
  frame.src = frameUrl();
  frame.style.width = `${device.frame.width * factor}px`;
  frame.style.height = `${device.frame.height * factor}px`;
  // Cleared before alignPixelGrid measures, so it reads the surface where
  // layout put it rather than where the last correction left it.
  surface.style.left = surface.style.top = "";
  syncFrameTint();
  alignPixelGrid();
  syncPreviewColumns();
}

function tone(value, low, high) {
  const index = LEVELS.findIndex(level => value <= level);
  if (index === 0) return low;
  if (index < 0) return high;
  const start = LEVELS[index - 1], end = LEVELS[index];
  const fraction = (value - start) / (end - start);
  const ratio = LEVEL_RATIOS[index - 1] +
    fraction * (LEVEL_RATIOS[index] - LEVEL_RATIOS[index - 1]);
  return Math.round(low + ratio * (high - low));
}

// Measured off the white device photographed on white paper in shade, each
// patch balanced against paper at its own height: the body reads a cast of
// (+0.7, +1.8, -2.4) and its e-ink panel (+1.0, +1.3, -2.4). Body and paper are
// the same hue, so one transform serves both, and the rendered device frames
// carry this same constant baked in.
//
// The two knobs are that cast's chromatic plane and nothing else: warm is how
// far red sits above blue, tint how far green sits above their mean. What they
// cannot express is a change in level, which is the point -- paper and ink own
// that, and an offset carrying a lightness term would let these fight them.
// Each channel triple sums to zero for the same reason.
//
// Nor is two a loss of reach: an offset triple has three degrees of freedom and
// one of them is lightness, so this covers every hue those three can reach. The
// shipped pair reproduces the measured (+1, +2, -2) exactly at every level from
// 0 to 255 once rounded, which is what keeps zero on both a true neutral grey
// and the default the calibrated one.
const WARM_CAST = 3, TINT_CAST = 2.5;

function castFor(warmth, greenness) {
  return [warmth / 2 - greenness / 3, greenness * 2 / 3,
          -warmth / 2 - greenness / 3];
}

// What fb2xt's frame renderer baked into every frame PNG. Computed from the
// constants above rather than written out again, so syncFrameTint can compare
// against it exactly: same expression and same inputs give the same doubles,
// and the shipped position is the one case that must come out as no filter.
const BAKED = castFor(WARM_CAST, TINT_CAST);

function cast() {
  return castFor(numberOf(warm), numberOf(tint));
}

// How far the knobs sit from what the frames were rendered with, per channel.
// All three are zero at the shipped position, and that is the case both callers
// turn on: no filter over the image, and no pass over its pixels.
function castDelta() {
  return cast().map((offset, channel) => offset - BAKED[channel]);
}

function rgb(level) {
  return cast().map(offset =>
    Math.max(0, Math.min(255, Math.round(level + offset))));
}

// The frames already carry BAKED, so only the difference is applied, and at the
// shipped values there is none: no filter at all, and the image draws as the
// exact pixels the render was calibrated to. A black body is tinted along with
// a white one. At level 13 it is barely visible, but skipping it would be a
// branch that buys nothing.
//
// Pixels that clipped at 255 when the cast was baked cannot be walked back
// exactly, so a few specular highlights keep a trace of it. The renderer's own
// guard holds those under 2% of the body.
function syncFrameTint() {
  const delta = castDelta();
  const changed = delta.some(Boolean);
  frame.style.filter = changed ? "url(#frame-tint)" : "";
  if (!changed) return;
  for (const [channel, func] of tintFuncs.entries()) {
    func.setAttribute("intercept", String(delta[channel] / 255));
  }
}

// --- the preview as a file ------------------------------------------------
// Always built from the 1:1 render, whatever scale the page is showing. That
// frame's aperture is the panel's own size, so the page goes in at its own
// pixels and nothing on the way out is resampled -- where compositing into the
// tall frame would stretch 480 columns of type across 873.

// The frame's cast is a filter over the image, and drawImage does not carry CSS
// filters, so the copy applies the same difference in pixels. Only where there
// is something to see: the transparent surround has no colour to shift. Sized
// from the image rather than from the record, so a frame that ever disagreed
// with its record would land wrong rather than be silently stretched to fit.
function tintedFrame(image) {
  const sheet = document.createElement("canvas");
  sheet.width = image.naturalWidth;
  sheet.height = image.naturalHeight;
  const context = sheet.getContext("2d");
  context.drawImage(image, 0, 0);
  const delta = castDelta();
  if (!delta.some(Boolean)) return sheet;
  const pixels = context.getImageData(0, 0, sheet.width, sheet.height);
  const data = pixels.data;
  for (let at = 0; at < data.length; at += 4) {
    if (!data[at + 3]) continue;
    for (let channel = 0; channel < 3; ++channel) {
      data[at + channel] = Math.max(0, Math.min(255,
        Math.round(data[at + channel] + delta[channel])));
    }
  }
  context.putImageData(pixels, 0, 0);
  return sheet;
}

async function decoded(url) {
  const image = new Image();
  image.src = url;
  await image.decode();
  return image;
}

// What the preview is showing, at the panel's own resolution: the body around
// the page when the frame is on, the page alone when it is off. The frame
// toggle is the whole of the choice, which is what it already means on screen.
//
// Nothing is painted behind it. The frames are rendered against transparency
// and the bare screen is clipped to its own corners, so what comes out is the
// device cut out of its surround and drops onto whatever it is put on. The
// place it is pasted into decides what shows through, which is the point: a
// background chosen here would be a rectangle to crop off everywhere else.
//
// Exported so it can be measured in a browser. Neither suite can: the JS one
// runs against a stub DOM with no canvas, and pytest never opens a page, so a
// composite that came out wrong would pass both.
// The toned page as something that can be drawn. It is held as pixels, and
// pixels can only be written straight into a canvas, which would ignore the
// rounded corners the bare screen is clipped to.
function tonedPage() {
  const sheet = document.createElement("canvas");
  sheet.width = toned.width;
  sheet.height = toned.height;
  sheet.getContext("2d").putImageData(toned, 0, 0);
  return sheet;
}

export async function deviceImage() {
  if (!toned) throw new Error("there is no page to copy yet");
  const device = profile("pixels");
  const framed = frameShown.checked;
  const sheet = document.createElement("canvas");
  sheet.width = framed ? device.frame.width : device.native.width;
  sheet.height = framed ? device.frame.height : device.native.height;
  const context = sheet.getContext("2d");
  if (!framed) {
    // Rounded off the way the screen is shown, rather than a bare rectangle.
    context.beginPath();
    context.roundRect(0, 0, sheet.width, sheet.height, device.aperture.radius);
    context.clip();
    context.drawImage(tonedPage(), 0, 0);
    return sheet;
  }
  context.drawImage(tonedPage(), device.aperture.x, device.aperture.y,
                    device.aperture.width, device.aperture.height);
  context.drawImage(tintedFrame(await decoded(frameUrl("pixels"))), 0, 0);
  return sheet;
}

async function deviceBlob() {
  const sheet = await deviceImage();
  const blob = await new Promise(resolve => sheet.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("the preview could not be encoded");
  return blob;
}

function imageName() {
  return `crossglyph-${model.value}`
         + `${frameShown.checked ? `-${color.value}` : "-page"}.png`;
}

// What the press will do, which depends on a key rather than on any state of
// its own. The copy wording is the markup's, so the two cannot drift.
const COPY_TITLE = copyButton.title;
const DOWNLOAD_TITLE = "Download the preview as an image. Let go of Shift to copy.";
let shiftHeld = false;
let restoreTitle = null;

function showCopyState() {
  copyButton.querySelector(".as-copy").hidden = shiftHeld;
  copyButton.querySelector(".as-download").hidden = !shiftHeld;
  copyButton.title = shiftHeld ? DOWNLOAD_TITLE : COPY_TITLE;
}

// A clipboard write leaves nothing on screen, so the button says what happened
// and then goes back to saying what it does. It goes back by re-running the
// state above rather than by restoring whatever the title was: a second press
// inside the delay would otherwise capture "copied" as the thing to return to,
// and the button would keep saying it for good.
function said(text, ok) {
  clearTimeout(restoreTitle);
  copyButton.classList.toggle("done", ok);
  copyButton.title = text;
  restoreTitle = setTimeout(() => {
    copyButton.classList.remove("done");
    showCopyState();
  }, 1200);
}

function failed(error) {
  said(String((error && error.message) || error), false);
}

// The clipboard is a secure-context API, and this preview is documented as
// serving to a network on --host 0.0.0.0, where a plain http page has neither
// navigator.clipboard nor ClipboardItem. Saying so beats a press that throws
// and looks like nothing happened -- and the other half of the button still
// works there, since an object URL needs no such thing.
function canCopy() {
  return typeof ClipboardItem === "function"
         && typeof navigator.clipboard?.write === "function";
}

// The ClipboardItem takes the promise rather than an awaited blob: Safari wants
// it built in the same turn as the press, and the encode is asynchronous.
async function copyDeviceImage() {
  if (!canCopy()) {
    throw new Error("copying needs https or localhost, so hold Shift to save");
  }
  await navigator.clipboard.write(
    [new ClipboardItem({"image/png": deviceBlob()})]);
  said("copied", true);
}

async function downloadDeviceImage() {
  const link = document.createElement("a");
  const url = URL.createObjectURL(await deviceBlob());
  link.href = url;
  link.download = imageName();
  link.click();
  // Not straight after the click: the download reads the blob through this URL,
  // and revoking it in the same turn is a race the save can lose.
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  said("saved", true);
}

//: The decoded page the canvas draws, replaced whole by each render. A bitmap
//: rather than an <img>: an element brings a src whose load and decode are
//: asynchronous state of their own, and every await on them is a place a
//: flaky decoder can strand the pipeline.
let page = null;

//: The page with the paper and ink applied, at the panel's own size, as the
//: pixels themselves rather than a canvas. The screen scales this to whatever
//: the mode asks for and the copy takes it whole, so both read one set of
//: pixels and a saved file cannot come out depending on the zoom the screen
//: happened to be at. Kept rather than built again each time because applying
//: the two tones walks every pixel, while the size on screen changes on every
//: drag of the window edge.
let toned = null;

// What each destination pixel takes from the source, as a run of weights: the
// source pixels its own width covers, each weighted by how much of it falls
// inside. Worked out once per axis, since every row wants the same answer.
function contributions(from, to) {
  const step = from / to;
  const starts = new Int32Array(to);
  const counts = new Int32Array(to);
  const weights = [];
  for (let at = 0; at < to; ++at) {
    const low = at * step, high = low + step;
    const first = Math.max(0, Math.floor(low));
    const last = Math.min(from, Math.ceil(high));
    starts[at] = first;
    counts[at] = last - first;
    for (let source = first; source < last; ++source) {
      weights.push(Math.min(source + 1, high) - Math.max(source, low));
    }
  }
  return {starts, counts, weights: Float32Array.from(weights)};
}

// Resample by area: a destination pixel is the mean of the source it covers.
//
// One filter serves both directions, which is why there is no second one for
// enlarging. Enlarging leaves most destination pixels sitting inside a single
// source pixel, and those hold that pixel exactly, so the strokes stay hard and
// only the boundaries between two source pixels blend. Bilinear softens the
// whole glyph instead, and a sharper filter overshoots and leaves a pale halo
// around every letter. Shrinking averages, so a stroke thinner than a
// destination pixel arrives at part weight rather than being kept whole or
// dropped whole, which is what nearest neighbour does to it, and why small text
// breaks up into a different thickness every few letters.
//
// The browser will not do this one. Its own smoothing is a sharper filter that
// haloes, and the quality hint that is supposed to choose between filters is
// read and ignored: low, medium and high come back byte for byte the same.
//
// Separable, so it costs two passes over the picture rather than one over every
// pair of pixels.
//: Scratch for the pass between the two, and the picture the second one fills.
//: Both are kept: dragging a window edge resamples on every frame, and handing
//: back several megabytes each time to ask for them again is most of what that
//: costs. Grown when a bigger size comes along and never shrunk.
let between = null;
let resampled = null;

function scratch(size) {
  if (!between || between.length < size) between = new Float32Array(size);
  return between;
}

function resampleByArea(data, from, to, out) {
  const across = contributions(from.width, to.width);
  const down = contributions(from.height, to.height);
  const wide = scratch(to.width * from.height * 3);
  // A destination pixel that covers exactly one source pixel is that pixel, so
  // the weights cancel and there is nothing to add up. Enlarging makes that
  // almost every pixel, which is the difference between this being noticeable
  // while a window edge is dragged and not being.
  for (let y = 0; y < from.height; ++y) {
    const row = y * from.width;
    const line = y * to.width;
    let weight = 0;
    for (let x = 0; x < to.width; ++x) {
      const count = across.counts[x];
      const start = across.starts[x];
      const at = (line + x) * 3;
      if (count === 1) {
        const one = (row + start) * 4;
        wide[at] = data[one];
        wide[at + 1] = data[one + 1];
        wide[at + 2] = data[one + 2];
      } else {
        let red = 0, green = 0, blue = 0, total = 0;
        for (let n = 0; n < count; ++n) {
          const share = across.weights[weight + n];
          const from4 = (row + start + n) * 4;
          red += data[from4] * share;
          green += data[from4 + 1] * share;
          blue += data[from4 + 2] * share;
          total += share;
        }
        wide[at] = red / total;
        wide[at + 1] = green / total;
        wide[at + 2] = blue / total;
      }
      weight += count;
    }
  }
  let weight = 0;
  for (let y = 0; y < to.height; ++y) {
    const count = down.counts[y];
    const start = down.starts[y];
    const line = y * to.width;
    for (let x = 0; x < to.width; ++x) {
      const at = (line + x) * 4;
      if (count === 1) {
        const one = (start * to.width + x) * 3;
        out[at] = wide[one];
        out[at + 1] = wide[one + 1];
        out[at + 2] = wide[one + 2];
      } else {
        let red = 0, green = 0, blue = 0, total = 0;
        for (let n = 0; n < count; ++n) {
          const share = down.weights[weight + n];
          const from3 = ((start + n) * to.width + x) * 3;
          red += wide[from3] * share;
          green += wide[from3 + 1] * share;
          blue += wide[from3 + 2] * share;
          total += share;
        }
        out[at] = red / total;
        out[at + 1] = green / total;
        out[at + 2] = blue / total;
      }
      out[at + 3] = 255;
    }
    weight += count;
  }
  return out;
}

// The rendered page with the two tones applied, at the panel's own size. The
// canvas is the scratch it is done on, and drawDevicePage puts the result back
// at the size the screen wants.
function tonePage() {
  if (!page || typeof canvas.getContext !== "function") return null;
  const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
  canvas.width = page.width;
  canvas.height = page.height;
  context.imageSmoothingEnabled = false;
  context.drawImage(page, 0, 0);
  const pixels = context.getImageData(0, 0, page.width, page.height);
  // Both controls measure "more": more paper is lighter, more ink is darker.
  const paperLevel = Math.round(Number(paper.value) * 255 / 100);
  const inkLevel = Math.round((100 - Number(ink.value)) * 255 / 100);
  const inkRgb = rgb(inkLevel), paperRgb = rgb(paperLevel);
  const palette = new Uint8ClampedArray(256 * 3);
  for (let source = 0; source < 256; ++source) {
    const base = source * 3;
    for (let channel = 0; channel < 3; ++channel) {
      palette[base + channel] =
        tone(source, inkRgb[channel], paperRgb[channel]);
    }
  }
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    const base = pixels.data[offset] * 3;
    pixels.data[offset] = palette[base];
    pixels.data[offset + 1] = palette[base + 1];
    pixels.data[offset + 2] = palette[base + 2];
    pixels.data[offset + 3] = 255;
  }
  return pixels;
}

// The toned page at the size it takes on this screen, counted in real pixels of
// it. Filling a canvas of that size here, rather than handing the browser a
// panel-sized one and letting it scale, is what puts the choice of filter in
// this file instead of in the browser's.
function drawDevicePage() {
  if (!toned || typeof canvas.getContext !== "function") return;
  const device = profile();
  const factor = sourceFactor(device, frameShown.checked) * dpr();
  const to = {
    width: Math.max(1, Math.round(device.aperture.width * factor)),
    height: Math.max(1, Math.round(device.aperture.height * factor)),
  };
  const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
  canvas.width = to.width;
  canvas.height = to.height;
  context.imageSmoothingEnabled = false;
  if (to.width === toned.width && to.height === toned.height) {
    // The page is at its own size, where resampling is an identity that costs a
    // pass over every pixel and risks not being one.
    context.putImageData(toned, 0, 0);
  } else {
    if (!resampled || resampled.width !== to.width ||
        resampled.height !== to.height) {
      resampled = context.createImageData(to.width, to.height);
    }
    resampleByArea(toned.data, toned, to, resampled.data);
    context.putImageData(resampled, 0, 0);
  }
  canvas.classList.add("shown");
}

export function paintDevicePage() {
  toned = tonePage();
  drawDevicePage();
}

export function showRenderedPage(bitmap) {
  if (page && typeof page.close === "function") page.close();
  page = bitmap;
  toned = tonePage();
  layoutDevice();
}

// What the markup declares a control to be, which is what both the panel's own
// reset and the per-knob arrows put back. One answer for three kinds of
// control, because two copies of this would be two chances to disagree about
// what "default" means.
function declaredValue(control) {
  if (control.type === "checkbox") return control.defaultChecked;
  if (control.tagName === "SELECT") {
    const declared = [...control.options].find(item => item.defaultSelected);
    return (declared || control.options[0]).value;
  }
  return control.defaultValue;
}

function putDeclared(control) {
  if (control.type === "checkbox") control.checked = declaredValue(control);
  else control.value = declaredValue(control);
}

function resetsFor(field) {
  return document.querySelectorAll(`[data-device-reset="${field.id}"]`);
}

// Which knobs carry an arrow is the markup's to say, and it says it by putting
// one there: every number does, and scale does not, being a dropdown that
// already shows every value it has. Asking the page rather than keeping a list
// beside it is what stops an arrow being added to a row and never lit, since
// the wiring in wireNumber already finds them this way.
//
// One is offered only while its knob differs from what the markup declares, so
// the column is empty on a panel nobody has touched.
function refreshDeviceResets() {
  for (const arrow of document.querySelectorAll("[data-device-reset]")) {
    const field = document.getElementById(arrow.dataset.deviceReset);
    if (!field) continue;
    const declared = declaredValue(field);
    arrow.hidden = Number(field.value) === Number(declared);
    arrow.title = `Reset to ${declared}`;
  }
}

function syncNumericControls() {
  for (const field of [paper, ink, warm, tint, calibrationRange]) {
    showSlider(field);
  }
  refreshDeviceResets();
  calibration.hidden = scale.value !== "custom";
  ruler.style.width = `${100 * CSS_PIXELS_PER_MM *
    Number(calibrationRange.value) / 100}px`;
}

function values() {
  const state = {
    device: model.value, frame: frameShown.checked, scale: scale.value,
    paper: paper.value, ink: ink.value, calibration: calibrationRange.value,
    warm: warm.value, tint: tint.value,
  };
  if (fixedColor) state.color = color.value;
  return state;
}

function saveDevice() {
  attempt(() => localStorage.setItem(DEVICE_STORE, JSON.stringify(values())));
}

function wireNumber(field, slider, changed) {
  const set = (control, value) => setNumeric(control, value, changed);
  pairSlider(field, slider, set);
  for (const button of document.querySelectorAll(`[data-for="${field.id}"]`)) {
    wireStepper(button, field, Number(button.dataset.dir), set);
  }
  // A reset rather than the bypass the tuning knobs carry. Those compare your
  // value with what a .conf says and are worth flicking between; these have no
  // config behind them, only the value the markup declares, so there is no
  // second value to hold on to. Through `set`, so the slider, the store and the
  // repaint all happen the way they do for any other edit.
  for (const arrow of resetsFor(field)) {
    arrow.addEventListener(
      "click", () => set(field, Number(declaredValue(field))));
  }
  field.addEventListener("input", () => {
    const value = Number(field.value);
    if (field.value !== "" && Number.isFinite(value)) {
      showSlider(field);
      changed(field);
    }
  });
  field.addEventListener("change", () => set(field, numberOf(field)));
}

function validOption(select, value) {
  return [...select.options].some(option => option.value === String(value));
}

export function loadDevice() {
  fixedColor = false;
  const raw = attempt(() => localStorage.getItem(DEVICE_STORE), null);
  if (raw) {
    let saved = null;
    try { saved = JSON.parse(raw); } catch {}
    if (saved && typeof saved === "object") {
      if (validOption(model, saved.device)) model.value = saved.device;
      if (validOption(color, saved.color)) {
        color.value = saved.color;
        fixedColor = true;
      }
      if (validOption(scale, saved.scale)) scale.value = saved.scale;
      if (typeof saved.frame === "boolean") frameShown.checked = saved.frame;
      for (const [control, value] of [[paper, saved.paper], [ink, saved.ink],
                                      [calibrationRange, saved.calibration],
                                      [warm, saved.warm], [tint, saved.tint]]) {
        const number = Number(value);
        if (Number.isFinite(number) && number >= Number(control.min) &&
            number <= Number(control.max)) control.value = String(number);
      }
    }
  }
  if (!fixedColor) color.value = themeColor();
  syncNumericControls();
  layoutDevice();
}

function resetDevice(scheduleRender) {
  const changedDevice = model.value !== declaredValue(model);
  for (const control of document.querySelectorAll("[data-device-setting]")) {
    putDeclared(control);
  }
  fixedColor = false;
  color.value = themeColor();
  attempt(() => localStorage.removeItem(DEVICE_STORE));
  syncNumericControls();
  toned = tonePage();
  layoutDevice();
  if (changedDevice) scheduleRender();
}

export function wireDevice(scheduleRender) {
  model.addEventListener("change", () => {
    saveDevice();
    layoutDevice();
    scheduleRender();
  });
  color.addEventListener("change", () => {
    fixedColor = true;
    saveDevice();
    layoutDevice();
  });
  frameShown.addEventListener("input", () => {
    saveDevice();
    layoutDevice();
  });
  scale.addEventListener("change", () => {
    syncNumericControls();
    saveDevice();
    layoutDevice();
  });
  const toneChanged = () => {
    saveDevice();
    refreshDeviceResets();
    paintDevicePage();
  };
  // The cast reaches the frame as well as the page, and the frame is not
  // repainted -- it is one image with a filter over it.
  const castChanged = () => {
    toneChanged();
    syncFrameTint();
  };
  wireNumber(paper, paperSlider, toneChanged);
  wireNumber(ink, inkSlider, toneChanged);
  wireNumber(warm, warmSlider, castChanged);
  wireNumber(tint, tintSlider, castChanged);
  wireNumber(calibrationRange, calibrationSlider, () => {
    syncNumericControls();
    saveDevice();
    layoutDevice();
  });
  reset.addEventListener("click", () => resetDevice(scheduleRender));
  // Called inside the press rather than after an await, so the gesture is still
  // the browser's reason for allowing a clipboard write. Both are async, so a
  // throw either side of the first await arrives here as a rejection and the
  // button says it, instead of going nowhere.
  copyButton.addEventListener("click", (event) => {
    (event.shiftKey ? downloadDeviceImage() : copyDeviceImage()).catch(failed);
  });
  // Say what the press will do for as long as the key is held, the same way
  // Build says Rebuild.
  for (const [kind, held] of [["keydown", true], ["keyup", false]]) {
    document.addEventListener(kind, (event) => {
      if (event.key !== "Shift") return;
      shiftHeld = held;
      showCopyState();
    });
  }
  globalThis.addEventListener?.("resize", layoutDevice);
}
