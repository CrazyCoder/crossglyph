import {form} from "./dom.js";
import {exportForm, exportSettings} from "./export.js";
import {familyEntries, familyPicker, shownFamily} from "./family.js";
import {body} from "./render.js";
import {KNOB_KEYS, knobModified, refreshReverts, rememberSaved, stashed} from "./reverts.js";
import {compare} from "./untuned.js";
import {WEIGHT_SLOTS, axesDiffer, axisSettings, variableSpec, rememberVariable} from "./variable.js";

// --- saving to the family's own config ------------------------------------
// The knobs start at what the family is set to and go back there, which makes
// the .conf the persistence layer rather than the browser: build the family
// for real and it uses what you tuned here, with no numbers copied by hand.
//
// Explicit rather than on every change. This is a panel you turn wildly to see
// what happens, the font source folder is not under version control, and a
// slider drag would otherwise write forty times into the file that decides
// what ships.
export const saveButton = document.getElementById("save");
export const savedNote = document.getElementById("saved");

// Compared, not remembered: a flag set by the first edit stays set when you
// put the value back, and then Save is lit with nothing to save. The panel is
// clean when it says what the config says, however it got there.
export function exportDiffers() {
  // The family the panel is *showing*, not the one the picker is set to. The
  // switch guard runs after the picker has already moved, so comparing against
  // its value asks whether this panel matches the family being switched to --
  // which it never does, and every switch claimed unsaved changes.
  const entry = familyEntries.get(shownFamily);
  if (!entry || !entry.export) return false;
  const now = exportSettings();
  return Object.keys(now).some(key => {
    // Coverage is a set of ticks either way round: the config may spell the
    // same two presets in the other order, and a panel that called that a
    // change would open dirty and never come clean.
    if (key === "intervals") {
      const parts = (text) => String(text ?? "").split(",")
                                                .filter(Boolean).sort().join();
      return parts(now[key]) !== parts(entry.export[key]);
    }
    return String(now[key] ?? "") !== String(entry.export[key] ?? "");
  });
}

// What a save would write, against what the config says. A knob being compared
// is not in it: the panel is showing the config's own value, so there is
// nothing to write for it, and a Save offering itself over a page that matches
// the file is an offer to do nothing.
export function knobsDiffer() {
  return exportDiffers() || axesDiffer() ||
    KNOB_KEYS.some(name => form.elements[name] && knobModified(name));
}

// The other question, which the family switch asks: is there work here that
// switching would throw away? A value set aside by a comparison is exactly
// that -- invisible on the page, and gone the moment another family loads.
export function unsavedWork() {
  return knobsDiffer() || stashed.size > 0;
}

export function showSaveState() {
  const entry = familyEntries.get(familyPicker.value);
  saveButton.hidden = !entry || !entry.conf;
  saveButton.disabled = !knobsDiffer();
  if (entry && entry.conf) {
    saveButton.textContent = entry.derived ? "Create " + entry.conf
                                           : "Save to " + entry.conf;
    saveButton.title = entry.derived
      ? entry.conf + " does not exist yet: all.conf covers this family. "
        + "Saving writes that file rather than retuning every family."
      : "Write these knobs into " + entry.conf + ", where the build reads them.";
  }
}

export async function saveKnobs() {
  // What is on the page is what gets written, including while a comparison is
  // running: the page is the only thing saying what this font will look like,
  // and a button that wrote something else -- a value set aside a minute ago,
  // which nothing on screen shows -- would be a save you cannot check.
  const family = familyPicker.value;
  const knobs = body().tuning;
  const settings = exportForm.hidden ? undefined : exportSettings();
  const axes = variableSpec ? axisSettings() : undefined;
  savedNote.textContent = "saving\u2026";
  let response;
  try {
    response = await fetch("/save", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify({family: family, tuning: knobs, export: settings,
                            axes: axes})});
  } catch (error) {
    savedNote.textContent = String(error);
    return false;
  }
  if (!response.ok) {
    savedNote.textContent = await response.text();
    return false;
  }

  const result = await response.json();
  rememberSaved(result.tuning);
  // The comparison is over, whatever state it was in: the page and the file
  // now say the same thing, so the values it had set aside are answers to a
  // question that no longer exists. Dropping them rather than putting them
  // back is the same rule as above -- what you saved is what you have.
  stashed.clear();
  compare.setAttribute("aria-pressed", "false");
  const entry = familyEntries.get(family);
  if (entry) {
    entry.tuning = result.tuning;
    entry.derived = false;
    if (settings) entry.export = {...entry.export, ...settings};
    // The file now says what the pickers say, so the panel is clean against it.
    if (axes && entry.variable) {
      entry.variable = {
        ...entry.variable,
        weights: Object.fromEntries(
          Object.entries(entry.variable.weights).map(
            ([slot, was]) => [slot, axes[slot] ?? was])),
        other: {...entry.variable.other,
                ...Object.fromEntries(Object.entries(axes).filter(
                  ([tag]) => !WEIGHT_SLOTS.includes(tag)))},
      };
      rememberVariable(entry.variable);
    }
  }
  savedNote.textContent = result.moved.length
    ? result.moved.join(", ") + " \u2192 " + result.conf
    : result.conf + " already said that";
  refreshReverts();
  return true;
}

saveButton.addEventListener("click", saveKnobs);
