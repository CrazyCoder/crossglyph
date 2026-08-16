import {form, showFeatures, syncLineHeight} from "./dom.js";
import {fillFallbackPickers, showExport} from "./export.js";
import {FAMILY, familyEntries, familyLabel, familyPicker, offerSavedThresholds, showFaces, shownFamily, rememberShown} from "./family.js";
import {numericRow, showSlider} from "./knobs.js";
import {attempt} from "./remember.js";
import {renderNow, scheduleRender} from "./render.js";
import {KNOB_KEYS, baseState, putKnob, refreshReverts, rememberSaved, showRevertState, stashed} from "./reverts.js";
import {savedNote, showSaveState, unsavedWork} from "./save.js";

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
const axisButtons = new Map();
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
    options.push(new Option(`${one.name} ${one.wght}`, String(one.wght)));
  }
  // A weight no instance is named for still has to be selectable: a config can
  // pin one, and a font naming none at all falls back to the CSS numbers.
  if (value != null && !seen.has(value)) {
    options.push(new Option(String(value), String(value)));
  }
  picker.replaceChildren(...options);
  picker.value = value == null ? "" : String(value);
}

function axisKey(tag) { return `axis_${tag}`; }

function axisSpec(tag) {
  return variableSpec && variableSpec.axes.find(axis => axis.tag === tag);
}

function axisTarget(tag) {
  const axis = axisSpec(tag), field = axisFields.get(tag);
  if (!axis || !field) return null;
  const current = Number(field.value);
  const saved = Number(variableSpec.other[tag] ?? axis.default);
  if (current !== saved) return {value: saved, source: "config"};
  const factory = Number(axis.default);
  if (current !== factory) return {value: factory, source: "stock"};
  return null;
}

function setAxis(tag, value) {
  const field = axisFields.get(tag);
  if (!field) return;
  field.value = String(value);
  showSlider(field);
  onAxisChange();
}

export function refreshAxisReverts() {
  for (const [tag, button] of axisButtons) {
    showRevertState(button, stashed.get(axisKey(tag)), axisTarget(tag));
  }
}

function bypassAxis(tag, target = axisTarget(tag), untuned = false) {
  const field = axisFields.get(tag);
  if (!field || !target) return;
  stashed.set(axisKey(tag), {
    value: field.value, source: target.source, untuned,
  });
  setAxis(tag, target.value);
}

function restoreAxis(tag) {
  const key = axisKey(tag), held = stashed.get(key);
  if (!held) return;
  stashed.delete(key);
  setAxis(tag, held.value);
}

function bypassUntunedAxis(tag, value) {
  const key = axisKey(tag), held = stashed.get(key);
  if (held) {
    held.untuned = {value: axisFields.get(tag).value};
    setAxis(tag, value);
  } else {
    bypassAxis(tag, {value, source: "stock"}, true);
  }
}

function restoreUntunedAxis(tag) {
  const key = axisKey(tag), held = stashed.get(key);
  if (!held || !held.untuned) return;
  const value = held.untuned === true ? held.value : held.untuned.value;
  if (held.untuned === true) stashed.delete(key);
  else delete held.untuned;
  setAxis(tag, value);
}

function toggleAxis(tag) {
  if (stashed.has(axisKey(tag))) restoreAxis(tag); else bypassAxis(tag);
  refreshAxisReverts();
}

export function compareAxes(on) {
  for (const tag of axisFields.keys()) {
    const axis = axisSpec(tag), field = axisFields.get(tag);
    if (!axis || !field) continue;
    if (on) {
      if (Number(field.value) !== Number(axis.default)) {
        bypassUntunedAxis(tag, axis.default);
      }
    } else {
      restoreUntunedAxis(tag);
    }
  }
  refreshAxisReverts();
}

export function axisRow(axis, value) {
  const {row, field} = numericRow({
    label: axis.tag, min: axis.min, max: axis.max, value, id: `axis-${axis.tag}`,
    step: (axis.max - axis.min) > 20 ? "1" : "0.5",
    title: `${axis.tag}: ${axis.min} to ${axis.max}, ${axis.default} by default`,
  });
  field.name = axisKey(axis.tag);
  field.dataset.group = "axes";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "revert";
  button.dataset.state = "off";
  button.hidden = true;
  button.textContent = "\u21ba";
  button.setAttribute("aria-label", `compare ${axis.tag}`);
  button.addEventListener("click", () => toggleAxis(axis.tag));
  row.append(button);
  axisFields.set(axis.tag, field);
  axisButtons.set(axis.tag, button);
  return row;
}

export function showVariable(entry) {
  variableSpec = (entry && entry.variable) || null;
  variableBox.hidden = !variableSpec;
  axisFields.clear();
  axisButtons.clear();
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
  refreshAxisReverts();
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

// What a reset puts the axis controls back to. Not the markup, whose first
// option is the lightest weight the font has: the value a slot resets to is
// the one the family declares, which is its config's if it has one and the
// font's own named instance if it has not. The same value the compare arrows
// measure against, so a reset lands on a panel that reads as clean.
export function resetAxes() {
  for (const tag of axisFields.keys()) stashed.delete(axisKey(tag));
  const entry = familyEntries.get(shownFamily);
  if (entry) showVariable(entry);
}

// The two pickers. The sliders beside them are numericRow's business and go
// through knobChanged like every other field, which is where the save state
// and the coalesced redraw already come from.
export function onAxisChange() {
  refreshAxisReverts();
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
  // After the knobs are put back, since it is the family and not the values
  // that decides these: a reset restores what a knob is set to, never whether
  // the font can act on it.
  showFeatures(entry);
  savedNote.textContent = "";
  showFaces();
  // Options first: a <select> refuses a value none of its options carries, so
  // showing the saved choice before the list exists silently picks nothing.
  fillFallbackPickers();
  showExport(entry);
  showVariable(entry);
  refreshReverts();
}

//: The picker's options and the entries behind them, from what /defaults
//: reports. Rebuilt rather than added to, since a refresh has to lose a font
//: that left the folder as well as gain one that arrived.
function listFamilies(d) {
  familyEntries.clear();
  familyPicker.replaceChildren();
  // The app can be started on a bare file, which is no family and cannot be
  // one. It stays selectable as the empty value, at the top, under its own
  // filename -- otherwise choosing another font would strand it. It has no
  // config either, so its knobs compare against the converter's defaults.
  if (!d.family && d.font) {
    familyPicker.add(new Option(d.font, ""));
    familyEntries.set("", {faces: d.faces, tuning: null, conf: null});
  }
  for (const family of d.families) {
    familyPicker.add(new Option(familyLabel(family), family.name));
    familyEntries.set(family.name, family);
  }
}

export function fillFamilies(d) {
  listFamilies(d);
  if (!familyPicker.options.length) return;   // nothing to choose between
  const saved = attempt(() => localStorage.getItem(FAMILY), null);
  // A remembered name whose font has since left the folder falls back to what
  // the app was started on, rather than posting a name the server will refuse.
  const wanted = familyEntries.has(saved) ? saved : (d.family ?? "");
  familyPicker.value = familyEntries.has(wanted) ? wanted
                                                 : familyPicker.options[0].value;
  loadFamily();
}

// The folder, asked again, because the tab has come back and reaching the
// folder meant leaving the window. A font may have been dropped in, taken
// away, or retuned in an editor while the page was not looking.
//
// What you are tuning keeps its place and its knobs: the picker moving under
// you would be worse than a stale list, and unsaved knobs are the only thing
// on this page with nowhere else to live.
export function refreshFamilies(d) {
  const chosen = familyPicker.value;
  const before = familyEntries.get(chosen);
  // Against the entry the controls were loaded from. Once the new list lands,
  // an edit made on disk would otherwise look like unsaved work in the panel.
  const hadUnsavedWork = unsavedWork();
  listFamilies(d);
  if (!familyEntries.has(chosen)) {
    // Its files have gone, so there is nothing left to draw it with and the
    // picker settles the way a fresh page would.
    fillFamilies(d);
    renderNow();
    return;
  }
  familyPicker.value = chosen;
  const entry = familyEntries.get(chosen);
  // Nothing about this family moved, only the list around it. The common
  // case by far -- every return to the tab -- and it does nothing at all.
  if (JSON.stringify(before) === JSON.stringify(entry)) return;
  if (!hadUnsavedWork) {
    loadFamily();               // nothing of yours to lose: follow the file
    renderNow();
    return;
  }

  if (JSON.stringify(before && before.tuning)
      === JSON.stringify(entry.tuning)) {
    // The file's tuning did not move, but something else about the family did:
    // most often the file behind a slot was replaced. Re-show
    // what is read off the font, and draw again, because the page in front of
    // you was drawn with the face as it was. Not showExport -- it writes into
    // fields you may have typed in, which have nowhere else to live either.
    showFaces();
    showFeatures(entry);
    renderNow();
    return;
  }
  // Yours stay. The arrows compare against the file from here, so what the
  // note says and what the panel offers to revert to agree.
  rememberSaved(entry.tuning);
  refreshReverts();
  showSaveState();
  savedNote.textContent =
    (entry.conf || "the config") + " changed on disk. Your unsaved knobs are "
    + "still here, and the arrows now compare against the new file.";
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
