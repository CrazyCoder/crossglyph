import {form} from "./dom.js";

// --- remembering the reader's own settings --------------------------------
// The Page knobs are the ones each person has already set on their device, so
// re-entering them every visit is friction with nothing to show for it. Font
// knobs deliberately do not persist: those are the experiment, and starting
// them anywhere but the shipped defaults would make a session hard to reason
// about.
export const STORE = "crossglyph.page";

// Storage *throws* rather than returning null when a browser has it blocked --
// a private window, or site data turned off. A preview that cannot remember is
// still a working preview, so every access is best effort.
export function attempt(fn, fallback) {
  try { return fn(); } catch (error) { return fallback; }
}

export function pageControls() {
  return [...form.elements].filter(el => el.name && el.dataset.group === "page");
}

export function savePage() {
  const out = {};
  for (const el of pageControls()) {
    out[el.name] = el.type === "checkbox" ? el.checked : el.value;
  }
  attempt(() => localStorage.setItem(STORE, JSON.stringify(out)));
}

export function loadPage() {
  const raw = attempt(() => localStorage.getItem(STORE), null);
  if (!raw) return;
  let saved;
  try { saved = JSON.parse(raw); } catch (error) { return; }
  if (!saved || typeof saved !== "object") return;
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
}
