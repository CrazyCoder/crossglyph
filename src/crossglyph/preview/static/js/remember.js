import {form} from "./dom.js";

// --- remembering the reader's own settings --------------------------------
// The Page knobs are the ones each person has already set on their device, so
// re-entering them every visit is friction with nothing to show for it. Font
// tuning knobs deliberately do not persist: those are the experiment, and
// starting them anywhere but the shipped defaults would make a session hard
// to reason about.
export const STORE = "crossglyph.page";

// Storage *throws* rather than returning null when a browser has it blocked --
// a private window, or site data turned off. A preview that cannot remember is
// still a working preview, so every access is best effort.
export function attempt(fn, fallback) {
  try { return fn(); } catch (error) { return fallback; }
}

// Size is which view of the font is open, not tuning written to its config.
// Keep it apart from Page, whose Reset button deliberately forgets the reader's
// device settings without changing what font size they are looking at.
export const SIZE = "crossglyph.size";

function validSize(raw) {
  const el = form.elements.size;
  const value = Number(raw);
  if (raw === null || String(raw).trim() === "" || !Number.isFinite(value)) {
    return null;
  }
  const min = Number(el.min), max = Number(el.max);
  if ((Number.isFinite(min) && value < min) ||
      (Number.isFinite(max) && value > max)) return null;
  const step = Number(el.step) || 1;
  const base = Number.isFinite(min) ? min : 0;
  const steps = (value - base) / step;
  if (Math.abs(steps - Math.round(steps)) > 1e-9) return null;
  return String(value);
}

export function saveSize() {
  const value = validSize(form.elements.size.value);
  if (value !== null) attempt(() => localStorage.setItem(SIZE, value));
}

export function loadSize() {
  const value = validSize(attempt(() => localStorage.getItem(SIZE), null));
  if (value !== null) form.elements.size.value = value;
}

export function pageControls() {
  return [...form.elements].filter(el =>
    el.name && el.dataset.group === "page" && !el.dataset.deviceSetting);
}

export function savePage() {
  const out = {};
  for (const el of pageControls()) {
    out[el.name] = el.type === "checkbox" ? el.checked : el.value;
  }
  attempt(() => localStorage.setItem(STORE, JSON.stringify(out)));
}

// Answers whether anything was there to load, which is what tells a first
// visit from a later one. A visit that restores nothing is the only time the
// browser's own languages get a say in the page settings.
export function loadPage() {
  const raw = attempt(() => localStorage.getItem(STORE), null);
  if (!raw) return false;
  let saved;
  try { saved = JSON.parse(raw); } catch (error) { return false; }
  if (!saved || typeof saved !== "object") return false;
  for (const el of pageControls()) {
    if (!Object.hasOwn(saved, el.name)) continue;
    const value = saved[el.name];
    if (el.type === "checkbox") { el.checked = !!value; continue; }
    // A remembered option that no longer exists -- a language dropped, a knob
    // renamed -- would set selectedIndex to -1, blank the control and post an
    // empty string. Leave the device's default standing instead.
    if (el.tagName === "SELECT" &&
        ![...el.options].some(o => o.value === String(value))) continue;
    el.value = value;
  }
  return true;
}

// Which hyphenation language the browser asks for, or English. The languages
// come in preference order and a region is dropped, since the core's patterns
// are per language: `de-AT` hyphenates with the German ones.
export function preferredLanguage(languages) {
  const known = new Set([...form.elements.language.options].map(o => o.value));
  for (const raw of languages || []) {
    const base = String(raw).toLowerCase().split("-")[0];
    if (base && known.has(base)) return base;
  }
  return "en";
}

// Set the language *and* the markup default behind it, then leave it unsaved.
//
// Both halves matter. The revert arrow and Reset page settings read
// defaultSelected, so a language taken from the browser has to become the
// declared value too, or both would offer to send a German reader back to
// English for good. And nothing is written to storage: "no preference" has to
// stay distinct from "chose this", or a later change to how this is worked out
// could never reach anybody who had merely opened the page once.
export function declareLanguage(value) {
  const el = form.elements.language;
  for (const option of el.options) {
    option.defaultSelected = option.value === value;
  }
  el.value = value;
}
