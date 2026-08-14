import {form} from "./dom.js";
import {attempt} from "./remember.js";
import {savedTuning} from "./reverts.js";

// --- the font ------------------------------------------------------------
// Which specimen, rather than a setting of one: the app knows every family in
// the font source folder, so choosing between them should not mean restarting
// it. Remembered like the sample text -- what you are looking at, not
// something either Reset button has an opinion about.
export const FAMILY = "crossglyph.family";
export const familyPicker = document.getElementById("family");
export const familyEntries = new Map();
export let shownFamily = "";

//: Which family the page is currently set in.
export function rememberShown(value) { shownFamily = value; }

// The four styles in the order the container numbers them, with the CSS that
// sets each badge in the style it names.
export const STYLE_BADGES = [
  ["regular", "", ""],
  ["bold", "700", ""],
  ["italic", "", "italic"],
  ["bold italic", "700", "italic"],
];
export const styleBadges = document.getElementById("styles");

export function showFaces() {
  const entry = familyEntries.get(familyPicker.value);
  const loaded = new Set(entry ? entry.faces : []);
  const files = (entry && entry.files) || {};
  styleBadges.replaceChildren(...STYLE_BADGES.map(([face, weight, style]) => {
    const badge = document.createElement("span");
    badge.textContent = "A";
    badge.style.fontWeight = weight;
    badge.style.fontStyle = style;
    badge.dataset.loaded = loaded.has(face) ? "yes" : "no";
    badge.title = loaded.has(face)
      ? `${face}: ${files[face] || "loaded"}`
      : `${face}: not in this family — drawn as regular, as the device would`;
    return badge;
  }));
  const label = familyPicker.selectedOptions[0];
  document.title = label ? `${label.textContent} — CrossGlyph preview`
                         : "CrossGlyph preview";
  // The picker is capped, so a long name is cut short on the closed control.
  // Naming it here is what makes it readable without opening the list.
  familyPicker.title = (label ? `${label.textContent}\n` : "")
    + "Which family from the font source folder to set the page in";
}

// What the picker calls a family. The one the tool ships is offered whatever
// else is in the folder, and saying so on its entry is what keeps it from
// reading as a font you put there and forgot.
export function familyLabel(entry) {
  return entry.bundled ? `${entry.name} (bundled)` : entry.name;
}

// A save renamed the family under us. Everything here is keyed by the name a
// build produces, so the entry moves rather than being reloaded: the panel is
// already showing this family, and re-reading the folder would throw away the
// knobs it has open for the sake of values it would find unchanged.
export function renameFamily(from, to) {
  const entry = familyEntries.get(from);
  if (!entry || from === to) return;
  entry.name = to;
  familyEntries.delete(from);
  familyEntries.set(to, entry);
  for (const option of familyPicker.options) {
    if (option.value !== from) continue;
    option.value = to;
    option.textContent = familyLabel(entry);
  }
  familyPicker.value = to;
  rememberShown(to);
  // Remembered under the new name too, or the next visit asks for a family the
  // server no longer has and opens on whichever one it started with.
  attempt(() => localStorage.setItem(FAMILY, to));
  showFaces();
}

// Switching font replaces the knobs with what that family is set to: they are
// its settings and not the panel's, and carrying them across would mean
// looking at one family's tuning while the Save button offered to write it
// into another's config.
export function offerSavedThresholds() {
  const el = form.elements.thresholds;
  if (!el) return;
  for (const option of [...el.options]) {
    if (option.dataset.custom) option.remove();
  }
  const value = String((savedTuning && savedTuning.thresholds) || "");
  if (!value || [...el.options].some(option => option.value === value)) return;
  // A <select> refuses a value none of its options carries, so a config with
  // its own triple would otherwise load as a blank control that saved 4,8,12
  // back over it.
  const option = new Option(`custom (${value.split(",").join(", ")})`, value);
  option.dataset.custom = "yes";
  el.add(option);
}
