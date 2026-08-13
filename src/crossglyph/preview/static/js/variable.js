import {form, syncLineHeight} from "./dom.js";
import {fillFallbackPickers, showExport} from "./export.js";
import {FAMILY, familyEntries, familyPicker, offerSavedThresholds, showFaces, shownFamily, rememberShown} from "./family.js";
import {numericRow, sliders} from "./knobs.js";
import {attempt} from "./remember.js";
import {knobChanged, renderNow, scheduleRender} from "./render.js";
import {KNOB_KEYS, baseState, putKnob, refreshReverts, savedTuning, rememberSaved, stashed} from "./reverts.js";
import {savedNote, showSaveState, unsavedWork} from "./save.js";
import {compare} from "./untuned.js";

// --- variable fonts -------------------------------------------------------
// A variable font is several faces in one file, so which face a slot is drawn
// at is a choice rather than a property of the file. The pickers offer the
// font's own named instances: a weight has a name in the family it belongs to,
// and "Regular 400" says more than 400 does. The italic slots follow their
// roman, since a family's italic is its text weight in italic.
export const variableBox = document.getElementById("variable");
export const axisRows = document.getElementById("axis-rows");
export const WEIGHT_SLOTS = ["text", "bold"];
//: The axis tag each slider shows, rebuilt whenever the family changes.
export const axisFields = new Map();
export let variableSpec = null;

//: The axes and instances of the family on the page, or null for a static one.
export function rememberVariable(value) { variableSpec = value; }

export function weightPicker(slot) { return form.elements["axis_" + slot]; }

export function fillWeights(picker, instances, value) {
  const options = [];
  const seen = new Set();
  for (const one of instances) {
    if (one.wght == null || seen.has(one.wght)) continue;
    seen.add(one.wght);
    options.push(new Option(`${one.name} — ${one.wght}`, String(one.wght)));
  }
  // A weight no instance is named for still has to be selectable: a config can
  // pin one, and a font naming none at all falls back to the CSS numbers.
  if (value != null && !seen.has(value)) {
    options.push(new Option(String(value), String(value)));
  }
  picker.replaceChildren(...options);
  picker.value = value == null ? "" : String(value);
}

export function axisRow(axis, value) {
  const {row, field} = numericRow({
    label: axis.tag, min: axis.min, max: axis.max, value, id: `axis-${axis.tag}`,
    step: (axis.max - axis.min) > 20 ? "1" : "0.5",
    title: `${axis.tag}: ${axis.min} to ${axis.max}, ${axis.default} by default`,
  });
  axisFields.set(axis.tag, field);
  return row;
}

export function showVariable(entry) {
  variableSpec = (entry && entry.variable) || null;
  variableBox.hidden = !variableSpec;
  axisFields.clear();
  axisRows.replaceChildren();
  if (!variableSpec) return;
  for (const slot of WEIGHT_SLOTS) {
    const value = variableSpec.weights[slot];
    document.getElementById(`axis-${slot}-row`).hidden = value == null;
    fillWeights(weightPicker(slot), variableSpec.instances, value);
  }
  const rows = [];
  for (const axis of variableSpec.axes) {
    // wght is the two pickers above, and opsz never arrives: it follows the
    // size, and a control for it would be a second way to say what size this is.
    if (axis.tag === "wght") continue;
    rows.push(axisRow(axis, variableSpec.other[axis.tag] ?? axis.default));
  }
  axisRows.replaceChildren(...rows);
}

// What a render and a save carry: the two weights, then every other axis.
export function axisSettings() {
  if (!variableSpec) return {};
  const out = {};
  for (const slot of WEIGHT_SLOTS) {
    const picker = weightPicker(slot);
    if (variableSpec.weights[slot] != null && picker.value !== "") {
      out[slot] = Number(picker.value);
    }
  }
  for (const [tag, field] of axisFields) out[tag] = Number(field.value);
  return out;
}

// Compared against the config, like every other control: what the page shows
// is clean when it is what the file would build.
export function axesDiffer() {
  const entry = familyEntries.get(shownFamily);
  const spec = entry && entry.variable;
  if (!spec) return false;
  const now = axisSettings();
  return WEIGHT_SLOTS.some(slot => spec.weights[slot] != null
                                   && Number(spec.weights[slot]) !== now[slot])
    || [...axisFields.keys()].some(
      tag => Number(spec.other[tag] ?? NaN) !== now[tag]);
}

// The two pickers. The sliders beside them are numericRow's business and go
// through knobChanged like every other field, which is where the save state
// and the coalesced redraw already come from.
export function onAxisChange() {
  showSaveState();
  scheduleRender();
}

for (const slot of WEIGHT_SLOTS) {
  weightPicker(slot).addEventListener("change", onAxisChange);
}

export function loadFamily() {
  const entry = familyEntries.get(familyPicker.value);
  rememberSaved(entry ? entry.tuning : null);
  offerSavedThresholds();
  rememberShown(familyPicker.value);
  stashed.clear();
  for (const name of KNOB_KEYS) {
    if (form.elements[name]) putKnob(name, baseState(name));
  }
  syncLineHeight();
  savedNote.textContent = "";
  showFaces();
  // Options first: a <select> refuses a value none of its options carries, so
  // showing the saved choice before the list exists silently picks nothing.
  fillFallbackPickers();
  showExport(entry);
  showVariable(entry);
  refreshReverts();
}

export function fillFamilies(d) {
  // The app can be started on a bare file, which is no family and cannot be
  // one. It stays selectable as the empty value, at the top, under its own
  // filename -- otherwise choosing another font would strand it. It has no
  // config either, so its knobs compare against the converter's defaults.
  if (!d.family && d.font) {
    familyPicker.add(new Option(d.font, ""));
    familyEntries.set("", {faces: d.faces, tuning: null, conf: null});
  }
  for (const family of d.families) {
    familyPicker.add(new Option(family.name, family.name));
    familyEntries.set(family.name, family);
  }
  if (!familyPicker.options.length) return;   // nothing to choose between
  const saved = attempt(() => localStorage.getItem(FAMILY), null);
  // A remembered name whose font has since left the folder falls back to what
  // the app was started on, rather than posting a name the server will refuse.
  const wanted = familyEntries.has(saved) ? saved : (d.family ?? "");
  familyPicker.value = familyEntries.has(wanted) ? wanted
                                                 : familyPicker.options[0].value;
  loadFamily();
}

//: Wired by the entry point rather than on import: a module body runs
//: while its own imports may still be evaluating.
export function onFamilyChange() {
  // Unsaved knobs would be dropped by the load below, and they are the only
  // thing on this page with nowhere else to live -- including a value a
  // comparison has set aside, which is not on screen to be missed.
  if (unsavedWork() && !confirm(
        (shownFamily || "This font") + " has unsaved knob changes, and "
        + "switching discards them.")) {
    familyPicker.value = shownFamily;
    return;
  }
  attempt(() => localStorage.setItem(FAMILY, familyPicker.value));
  loadFamily();
  renderNow();
}
