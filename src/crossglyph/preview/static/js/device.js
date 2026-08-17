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

// Geometry is in each normalized frame PNG's own pixels. The assets correct the
// source renders to the documented body aspect and carry an aperture with the
// native screen aspect. Runtime scaling is therefore one uniform factor.
export const DEVICES = {
  x4: {
    native: {width: 480, height: 800},
    frame: {width: 1147, height: 1820},
    aperture: {x: 139, y: 114, width: 858, height: 1430, radius: 16},
    body: {x: 16, y: 16, width: 1115, height: 1788,
           widthMm: 69, heightMm: 111},
  },
  x3: {
    native: {width: 528, height: 792},
    frame: {width: 1204, height: 1820},
    aperture: {x: 134, y: 132, width: 936, height: 1404, radius: 16},
    body: {x: 16, y: 16, width: 1172, height: 1788,
           widthMm: 63.7, heightMm: 97.6},
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
// carry this same constant.
function rgb(level) {
  return [Math.min(255, level + 1), Math.min(255, level + 2),
          Math.max(0, level - 2)];
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
  for (const field of [paper, ink, calibrationRange]) showSlider(field);
  calibration.hidden = scale.value !== "custom";
  ruler.style.width = `${100 * CSS_PIXELS_PER_MM *
    Number(calibrationRange.value) / 100}px`;
}

function values() {
  const state = {
    device: model.value, frame: frameShown.checked, scale: scale.value,
    paper: paper.value, ink: ink.value, calibration: calibrationRange.value,
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
                                      [calibrationRange, saved.calibration]]) {
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
  wireNumber(paper, paperSlider, toneChanged);
  wireNumber(ink, inkSlider, toneChanged);
  wireNumber(calibrationRange, calibrationSlider, () => {
    syncNumericControls();
    saveDevice();
    layoutDevice();
  });
  reset.addEventListener("click", () => resetDevice(scheduleRender));
  globalThis.addEventListener?.("resize", layoutDevice);
}
