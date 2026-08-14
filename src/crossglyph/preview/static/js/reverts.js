import {form, lineHeightAuto, syncFeatures, syncLineHeight} from "./dom.js";
import {showSlider} from "./knobs.js";
import {knobChanged} from "./render.js";
import {showSaveState} from "./save.js";

// --- per-knob compare -----------------------------------------------------
// Reset and bypass are different things, and editing tools have always kept
// them apart: reset throws your value away, bypass sets it aside so you can
// put it back. Tuning wants the second -- flick between your value and the
// default as often as it takes, one click each way, without losing the value
// or having to find it again. So the arrow toggles rather than resets, and
// what it set aside lives here until you put it back or edit that knob
// yourself.
export const reverts = [...form.querySelectorAll(".revert")];
export const stashed = new Map();

//: A checkbox says the same thing without a button. Setting a value aside is
//: what the arrow is for, and a switch has nothing to set aside: the value it
//: is not showing is the other one, which is the click you would have spent on
//: the arrow anyway. So a binary knob gets a mark that says it differs and
//: from what, and no second way to flip it.
export const marks = [...form.querySelectorAll(".mark")];

// Three values a knob can have, and each control here needs all three:
//   factory  what the converter does with no config at all
//   saved    what the family's .conf says today, all.conf underneath it
//   current  what the panel is showing
// The arrow offers whichever of the first two the panel is not already
// showing -- see compareTarget. `untuned` and Reset go to factory, which is
// the only thing they have ever meant.
//
// A state carries all three controls a knob can involve, because line_height
// is a field and a checkbox saying to ignore it.
// In panel order, which is order of use: nothing here depends on it, but a
// list that reads differently from the thing it describes is one more place to
// check when a knob is added.
export const KNOB_KEYS = ["gamma", "weight", "line_height", "letter_spacing",
                   "word_spacing", "kerning", "slant", "thresholds", "hinting",
                   "grayscale_hinting", "stem_darkening", "ligatures",
                   "figures"];
export let savedTuning = null;             // the selected family's, null for a file

//: What the family's config says, for everything that compares with it.
export function rememberSaved(value) { savedTuning = value; }

export function declaredValue(el) {
  if (el.tagName !== "SELECT") return el.defaultValue;
  const declared = [...el.options].find(o => o.defaultSelected) ?? el.options[0];
  return declared ? declared.value : el.value;
}

// `checked` only ever means a checkbox: a <select> has no such property at
// all, so reading it raw would compare undefined against the false every other
// state carries and call the knob changed the moment the page loaded.
export function currentState(name) {
  const el = form.elements[name];
  return {value: el.value, checked: el.type === "checkbox" && el.checked,
          auto: name === "line_height" && lineHeightAuto.checked};
}

export function factoryState(name) {
  const el = form.elements[name];
  return {// A checkbox's `value` is not its state and none of these markup
          // boxes sets one, so `value` reads "on" while `defaultValue` reads
          // "" -- and comparing those two calls every checkbox on the page
          // changed, for good. `checked` is the whole of a checkbox's state,
          // and both sides have to agree on what is not being compared.
          value: el.type === "checkbox" ? el.value : declaredValue(el),
          checked: el.type === "checkbox" && el.defaultChecked,
          auto: name === "line_height" && lineHeightAuto.defaultChecked};
}

export function savedState(name) {
  if (!savedTuning || !(name in savedTuning)) return null;
  const value = savedTuning[name];
  const el = form.elements[name];
  // null line_height is the font's own hhea, which is the checkbox and not
  // any number the field could hold.
  if (name === "line_height") {
    return {value: value === null ? declaredValue(el) : String(value),
            checked: false, auto: value === null};
  }
  if (el.type === "checkbox") {
    return {value: el.value, checked: Boolean(value), auto: false};
  }
  return {value: String(value), checked: false, auto: false};
}

export function baseState(name) {
  return savedState(name) ?? factoryState(name);
}

// Which baseline this knob's arrow offers, and null when it has none left.
//
// The config, while what is shown differs from it: "undo what I just did to
// this knob" is what you reach for constantly. Saving makes the two agree on
// every knob at once, and an arrow that only knew that question would empty
// the whole column at the moment the font became worth reading -- so it falls
// through to factory, which is the other question worth asking of a saved
// font: what does this config change from stock. Leave a knob on factory and
// it differs from the config again, so the arrow points back the other way and
// the pair oscillates.
export function compareTarget(name) {
  const now = currentState(name);
  const saved = savedState(name);
  if (saved && !sameState(now, saved)) return {state: saved, source: "config"};
  const factory = factoryState(name);
  if (sameState(now, factory)) return null;
  return {state: factory, source: "stock"};
}

export function sameState(one, other) {
  if (one.checked !== other.checked || one.auto !== other.auto) return false;
  // Both on "the font's own" means equal whatever the field is parked at.
  if (one.auto) return true;
  return one.value === other.value ||
         (one.value !== "" && other.value !== "" &&
          Number(one.value) === Number(other.value));
}

// Assign without asking for a page, for the loops that set many knobs at once.
export function putKnob(name, state) {
  const el = form.elements[name];
  if (el.type === "checkbox") el.checked = state.checked;
  else el.value = state.value;
  if (name === "line_height") lineHeightAuto.checked = state.auto;
  showSlider(el);
}

export function setKnob(name, state) {
  putKnob(name, state);
  if (name === "line_height") syncLineHeight();
  // The same for hinting, which decides whether the switch under it can do
  // anything: a comparison moves knobs with no event for a listener to hear.
  if (name === "hinting") syncFeatures();
  knobChanged(form.elements[name]);
}

// The line-height field and its "font's own" toggle are one setting in two
// controls, so they carry one arrow between them -- which the state does too.
export function knobModified(name, base) {
  return !sameState(currentState(name), base ?? baseState(name));
}

export function refreshReverts() {
  for (const button of reverts) {
    const name = button.dataset.reset;
    const off = stashed.has(name);
    const target = compareTarget(name);
    button.hidden = !(off || target);
    button.dataset.state = off ? "on" : "off";
    const source = off ? stashed.get(name).source : target && target.source;
    const what = source === "stock" ? "the stock value" : "what the config has";
    // What pressing it does, in both states. It is a comparison rather than a
    // reset: your value is set aside, not thrown away.
    button.title = off
      ? `Showing ${what}. Click to put your value back.`
      : `Set your value aside and show ${what}. Click again to bring it back.`;
  }
  for (const mark of marks) {
    const target = compareTarget(mark.dataset.mark);
    mark.hidden = !target;
    if (!target) continue;
    const was = target.state.checked ? "on" : "off";
    mark.title = target.source === "config"
      ? `Changed. The config has this ${was}.`
      : `Changed from stock, which is ${was}.`;
  }
  showSaveState();
}

export function restoreKnob(name) {
  const held = stashed.get(name);
  if (!held) return;
  stashed.delete(name);
  setKnob(name, held);
}

export function bypassKnob(name, target, source) {
  // A caller naming a target has already said which baseline it wants; untuned
  // is the one that does, and factory is what it means.
  const pick = target ? {state: target, source: source ?? "stock"}
                      : compareTarget(name);
  if (!pick) return;
  // Stash before setting: setKnob renders, and the render has to already see
  // this knob as set aside or the arrow would hide itself. Which baseline is
  // being shown rides along in the same entry, so the arrow can name it while
  // it is pressed and the two cannot be dropped separately -- five places drop
  // a stash, and a second map beside it would have to be right in all of them.
  // setKnob reads value, checked and auto, and ignores the rest.
  stashed.set(name, {...currentState(name), source: pick.source});
  setKnob(name, pick.state);
}

for (const button of reverts) {
  button.addEventListener("click", () => {
    const name = button.dataset.reset;
    if (stashed.has(name)) restoreKnob(name); else bypassKnob(name);
    refreshReverts();
  });
}
