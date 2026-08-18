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
// line from appearing down each side. And 1:1 scales by native.width divided by
// aperture.width and applies that one factor to both axes, so an aperture of
// any other shape lands the page on fractional device pixels: the glass is
// 0.60304 against the panel's 0.6, which put 800 source rows into 796. The
// overhang tucks under the frame, which draws above the page.
export const DEVICES = {
  x4: {
    native: {width: 480, height: 800},
    frame: {width: 1118, height: 1820},
    aperture: {x: 117, y: 100, width: 873, height: 1455, radius: 16},
    body: {x: 8, y: 8, width: 1091, height: 1804,
           widthMm: 69.15, heightMm: 114.31},
  },
  x3: {
    native: {width: 528, height: 792},
    frame: {width: 1209, height: 1820},
    aperture: {x: 130, y: 122, width: 948, height: 1422, radius: 16},
    body: {x: 19, y: 19, width: 1171, height: 1793,
           widthMm: 63.74, heightMm: 97.59},
  },
};

const CSS_PIXELS_PER_MM = 96 / 25.4;
// XTEINK's accurate white X4 front photograph measures the display at
// 51, 105, 160 and 215. The black product photograph darkens the display and
// is only a reference for its frame.
const LEVELS = [0, 96, 200, 255];
const LEVEL_RATIOS = [0, .329, .665, 1];

function profile() {
  return DEVICES[model.value] || DEVICES.x4;
}

function dpr() {
  return Number(globalThis.devicePixelRatio) || 1;
}

function frameUrl() {
  return `device/${model.value}-${color.value}.png`;
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
  const offsets = cast();
  const changed = offsets.some((offset, channel) => offset !== BAKED[channel]);
  frame.style.filter = changed ? "url(#frame-tint)" : "";
  if (!changed) return;
  for (const [channel, func] of tintFuncs.entries()) {
    func.setAttribute("intercept",
                      String((offsets[channel] - BAKED[channel]) / 255));
  }
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

function syncNumericControls() {
  for (const field of [paper, ink, warm, tint, calibrationRange]) {
    showSlider(field);
  }
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
  const declaredDevice = [...model.options].find(option =>
    option.defaultSelected)?.value || model.options[0].value;
  const changedDevice = model.value !== declaredDevice;
  for (const control of document.querySelectorAll("[data-device-setting]")) {
    if (control.type === "checkbox") {
      control.checked = control.defaultChecked;
    } else if (control.tagName === "SELECT") {
      const option = [...control.options].find(item => item.defaultSelected);
      control.value = (option || control.options[0]).value;
    } else {
      control.value = control.defaultValue;
    }
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
  globalThis.addEventListener?.("resize", layoutDevice);
}
