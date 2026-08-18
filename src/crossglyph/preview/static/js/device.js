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

function alignPixelGrid() {
  if (scale.value !== "pixels" ||
      typeof canvas.getBoundingClientRect !== "function") return;
  const rect = canvas.getBoundingClientRect();
  const ratio = dpr();
  const dx = (Math.round(rect.left * ratio) - rect.left * ratio) / ratio;
  const dy = (Math.round(rect.top * ratio) - rect.top * ratio) / ratio;
  surface.style.transform = `translate(${dx}px, ${dy}px)`;
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
  frame.hidden = !shown;
  frame.src = frameUrl();
  frame.style.width = `${device.frame.width * factor}px`;
  frame.style.height = `${device.frame.height * factor}px`;
  surface.style.transform = "";
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

// What sits behind the body, and in the corners the screen is rounded off with.
//
// Not transparency, which is what a canvas starts as and what an asset exported
// from a drawing tool would carry. This is a picture of what is on screen, and
// it is pasted into places that flatten an alpha channel to white -- where a
// white device against white loses the edge these frames were re-rendered to
// give it. The surround it already has is the page's, so the picture takes it
// and follows the theme with it. The README screenshots are padded to the same
// grey for the same reason.
function stageColour() {
  return getComputedStyle(root).getPropertyValue("--stage").trim() || "#e6e6e6";
}

// What the preview is showing, at the panel's own resolution: the body around
// the page when the frame is on, the page alone when it is off. The frame
// toggle is the whole of the choice, which is what it already means on screen.
//
// Exported so it can be measured in a browser. Neither suite can: the JS one
// runs against a stub DOM with no canvas, and pytest never opens a page, so a
// composite that came out wrong would pass both.
export async function deviceImage() {
  const device = profile("pixels");
  const framed = frameShown.checked;
  const sheet = document.createElement("canvas");
  sheet.width = framed ? device.frame.width : device.native.width;
  sheet.height = framed ? device.frame.height : device.native.height;
  const context = sheet.getContext("2d");
  context.fillStyle = stageColour();
  context.fillRect(0, 0, sheet.width, sheet.height);
  if (!framed) {
    // Rounded off the way the screen is shown, rather than a bare rectangle.
    context.beginPath();
    context.roundRect(0, 0, sheet.width, sheet.height, device.aperture.radius);
    context.clip();
    context.drawImage(canvas, 0, 0);
    return sheet;
  }
  context.drawImage(canvas, device.aperture.x, device.aperture.y,
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

export function paintDevicePage() {
  if (!page || typeof canvas.getContext !== "function") return;
  const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
  canvas.width = page.width;
  canvas.height = page.height;
  context.imageSmoothingEnabled = false;
  context.drawImage(page, 0, 0);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
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
  context.putImageData(pixels, 0, 0);
  canvas.classList.add("shown");
}

export function showRenderedPage(bitmap) {
  if (page && typeof page.close === "function") page.close();
  page = bitmap;
  paintDevicePage();
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
// one there: scale has none, being a dropdown that already shows every value it
// has, and neither has the custom scale, which is a ruler measurement worth
// more than one click. Asking the page rather than keeping a list beside it is
// what stops an arrow being added to a row and never lit, since the wiring in
// wireNumber already finds them this way.
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
  paintDevicePage();
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
