import {img} from "./dom.js";
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
const ink = document.getElementById("device-ink");
const paperValue = document.getElementById("device-paper-value");
const inkValue = document.getElementById("device-ink-value");
const calibrate = document.getElementById("device-calibrate");
const calibration = document.getElementById("device-calibration");
const calibrationRange = document.getElementById("device-calibration-range");
const calibrationValue = document.getElementById("device-calibration-value");
const ruler = document.getElementById("device-ruler");
const reset = document.getElementById("reset-device");

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
  if (scale.value === "device") {
    const correction = Number(calibrationRange.value) / 100;
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
}

function tone(value, low, high) {
  let index = LEVELS.findIndex(level => value <= level);
  if (index <= 0) return low;
  if (index < 0) index = LEVELS.length - 1;
  const start = LEVELS[index - 1], end = LEVELS[index];
  const fraction = (value - start) / (end - start);
  const ratio = LEVEL_RATIOS[index - 1] +
    fraction * (LEVEL_RATIOS[index] - LEVEL_RATIOS[index - 1]);
  return Math.round(low + ratio * (high - low));
}

function rgb(level, paperTone) {
  return [Math.max(0, level - (paperTone ? 2 : 1)),
          Math.min(255, level + 1), level];
}

export function paintDevicePage() {
  if (!img.naturalWidth || typeof canvas.getContext !== "function") return;
  const context = canvas.getContext("2d", {alpha: false, willReadFrequently: true});
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  context.imageSmoothingEnabled = false;
  context.drawImage(img, 0, 0);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
  // Both controls measure "more": more paper is lighter, more ink is darker.
  const paperLevel = Math.round(Number(paper.value) * 255 / 100);
  const inkLevel = Math.round((100 - Number(ink.value)) * 255 / 100);
  const inkRgb = rgb(inkLevel, false), paperRgb = rgb(paperLevel, true);
  const cache = new Map();
  for (let offset = 0; offset < pixels.data.length; offset += 4) {
    const source = pixels.data[offset];
    let mapped = cache.get(source);
    if (!mapped) {
      mapped = inkRgb.map((channel, index) =>
        tone(source, channel, paperRgb[index]));
      cache.set(source, mapped);
    }
    pixels.data[offset] = mapped[0];
    pixels.data[offset + 1] = mapped[1];
    pixels.data[offset + 2] = mapped[2];
    pixels.data[offset + 3] = 255;
  }
  context.putImageData(pixels, 0, 0);
  canvas.classList.add("shown");
  layoutDevice();
}

export async function showRenderedPage() {
  try {
    if (typeof img.decode === "function") await img.decode();
  } catch {
    return;
  }
  paintDevicePage();
}

function syncReadouts() {
  paperValue.value = `${paper.value}%`;
  inkValue.value = `${ink.value}%`;
  calibrationValue.value = `${Number(calibrationRange.value)}%`;
  ruler.style.width = `${100 * CSS_PIXELS_PER_MM *
    Number(calibrationRange.value) / 100}px`;
}

function values() {
  return {
    device: model.value, color: color.value, frame: frameShown.checked,
    scale: scale.value, paper: paper.value, ink: ink.value,
    calibration: calibrationRange.value,
  };
}

function saveDevice() {
  attempt(() => localStorage.setItem(DEVICE_STORE, JSON.stringify(values())));
}

function validOption(select, value) {
  return [...select.options].some(option => option.value === String(value));
}

export function loadDevice() {
  const raw = attempt(() => localStorage.getItem(DEVICE_STORE), null);
  if (raw) {
    let saved = null;
    try { saved = JSON.parse(raw); } catch {}
    if (saved && typeof saved === "object") {
      if (validOption(model, saved.device)) model.value = saved.device;
      if (validOption(color, saved.color)) color.value = saved.color;
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
  syncReadouts();
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
  attempt(() => localStorage.removeItem(DEVICE_STORE));
  syncReadouts();
  paintDevicePage();
  layoutDevice();
  if (changedDevice) scheduleRender();
}

export function wireDevice(scheduleRender) {
  model.addEventListener("input", () => {
    saveDevice();
    layoutDevice();
    scheduleRender();
  });
  for (const control of [color, frameShown, scale]) {
    control.addEventListener("input", () => {
      saveDevice();
      layoutDevice();
    });
  }
  for (const control of [paper, ink]) {
    control.addEventListener("input", () => {
      syncReadouts();
      saveDevice();
      paintDevicePage();
    });
  }
  calibrationRange.addEventListener("input", () => {
    syncReadouts();
    saveDevice();
    layoutDevice();
  });
  calibrate.addEventListener("click", () => {
    const open = calibration.hidden;
    calibration.hidden = !open;
    calibrate.setAttribute("aria-expanded", String(open));
    if (open && scale.value !== "device") {
      scale.value = "device";
      saveDevice();
      layoutDevice();
    }
  });
  reset.addEventListener("click", () => resetDevice(scheduleRender));
  globalThis.addEventListener?.("resize", layoutDevice);
}
