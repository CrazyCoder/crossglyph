import {form} from "./dom.js";
import {knobChanged} from "./render.js";
import {stashed} from "./reverts.js";

// --- numeric fields -------------------------------------------------------
// Steppers rather than sliders. Gamma alone is 74 steps across its range, so a
// slider gives under three pixels a step and no way to land on a round number
// -- these knobs are read off and written into a .conf, so the value matters
// as much as the direction.
export const sliders = new Map();

export function decimalsOf(step) {
  const dot = String(step).indexOf(".");
  return dot < 0 ? 0 : String(step).length - dot - 1;
}

export function setNumeric(field, value, changed) {
  const step = Number(field.step) || 1;
  const min = field.min === "" ? -Infinity : Number(field.min);
  const max = field.max === "" ? Infinity : Number(field.max);
  // Snap to the step before clamping, or repeated arithmetic drifts into
  // 1.0500000000000003 and the field stops showing round numbers.
  const snapped = Math.round(value / step) * step;
  // toFixed does the rounding, String(Number(...)) drops the padding it adds:
  // a quarter-point knob should read 15 and 15.25, not 15.00, which is what
  // every type tool shows and what the markup's own defaults already say.
  const next = String(Number(
    Math.min(max, Math.max(min, snapped)).toFixed(decimalsOf(field.step))));
  if (next !== field.value) {
    field.value = next;
    changed(field);
  }
  // Unconditionally, so a drag that snapped or clamped does not leave the
  // slider sitting off the value it is showing.
  showSlider(field);
}

export function setField(field, value) {
  setNumeric(field, value, () => {
    // Same rule as editing the field by hand, and it has to be here too:
    // assigning .value fires no input event, so a knob moved with the steppers
    // would otherwise keep the value its arrow set aside and jump back to that
    // instead of to what you just dialled in. bypassKnob and restoreKnob
    // assign .value directly and never come through here, so this only ever
    // fires for a change you made.
    stashed.delete(field.name);
    knobChanged(field);
  });
}

// The slider's value and its filled track, which have to move together or the
// fill tells you one thing and the thumb another.
export function showSlider(field) {
  const slider = sliders.get(field);
  if (!slider) return;
  slider.value = field.value;
  const min = Number(slider.min), max = Number(slider.max);
  const fraction = max > min ? (Number(field.value) - min) / (max - min) : 0;
  slider.style.setProperty("--fill", `${Math.round(fraction * 100)}%`);
}

export function stepBy(field, direction, coarse, set = setField) {
  const step = (Number(field.step) || 1) * (coarse ? 10 : 1);
  set(field, Number(field.value) + step * direction);
}

// A held stepper repeats, which is what keeps a field as quick to sweep as the
// slider it replaced. A function rather than a loop body, because the axis
// rows a variable font brings are built after this runs and need the same.
export function wireStepper(button, field, direction, set = setField) {
  let delay = null, repeat = null;
  const stop = () => { clearTimeout(delay); clearInterval(repeat); repeat = null; };
  button.addEventListener("pointerdown", (event) => {
    if (field.disabled) return;
    const coarse = event.shiftKey;
    stepBy(field, direction, coarse, set);
    delay = setTimeout(() => {
      repeat = setInterval(() => stepBy(field, direction, coarse, set), 55);
    }, 400);
  });
  for (const kind of ["pointerup", "pointerleave", "pointercancel"]) {
    button.addEventListener(kind, stop);
  }
}

//: Wired by the entry point rather than on import: `form` belongs to dom.js,
//: and a module body can run while a module it imports is still evaluating.
export function wireKnobs() {
  for (const button of form.querySelectorAll("button.step")) {
    wireStepper(button, form.elements[button.dataset.for],
                Number(button.dataset.dir));
  }
  // The slider beside each field covers distance; the field lands on the
  // value. They are one control in two halves, so every path that moves one
  // moves both.
  for (const slider of form.querySelectorAll("[data-slider-for]")) {
    pairSlider(form.elements[slider.dataset.sliderFor], slider);
  }
  form.addEventListener("change", (event) => {
    if (event.target.type === "number") {
      setField(event.target, numberOf(event.target));
    }
  });
}

// The slider and the field are one control in two halves, and pairing them is
// what makes showSlider and setField work on either. Built rows register here
// the way the markup's own rows are registered below.
export function pairSlider(field, slider, set = setField) {
  sliders.set(field, slider);
  slider.addEventListener("input", () => set(field, Number(slider.value)));
}

// A numeric knob, built rather than declared: `− [ value ] +` with a slider
// beside it, wired exactly as the rows in the markup are.
//
// The markup declares the knobs that are always there; this is for the ones
// that depend on the font, which is the axes a variable family brings. Going
// through the same wiring is the point of it: a built row snaps to its step,
// clamps to its range, keeps its slider and field in step, takes shift for ten
// at a time, and asks for a page the one coalesced way -- none of which it
// gets by being assembled by hand somewhere else.
export function numericRow({label, min, max, step, value, title = "", id = ""}) {
  const row = document.createElement("div");
  row.className = "row num";
  const name = document.createElement("label");
  name.className = "name";
  name.textContent = label;
  if (title) name.title = title;

  const slider = document.createElement("input");
  const field = document.createElement("input");
  // The declared rows pair their label with their field, and a built row has
  // to as well: it is what makes the label clickable and what a screen reader
  // reads the field out as.
  if (id) { field.id = id; name.htmlFor = id; }
  for (const el of [slider, field]) {
    el.min = min; el.max = max; el.step = step;
    el.value = String(value);
  }
  slider.type = "range";
  slider.tabIndex = -1;
  slider.setAttribute("aria-hidden", "true");
  field.type = "number";
  field.className = "mono";
  field.inputMode = "decimal";
  if (title) field.title = title;

  const stepper = document.createElement("span");
  stepper.className = "stepper";
  const buttons = [-1, 1].map(direction => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "step mono";
    button.textContent = direction < 0 ? "−" : "+";
    button.setAttribute(
      "aria-label", `${direction < 0 ? "decrease" : "increase"} ${label}`);
    wireStepper(button, field, direction);
    return button;
  });
  stepper.append(buttons[0], field, buttons[1]);

  row.append(name, slider, stepper);
  pairSlider(field, slider);
  showSlider(field);
  return {row, field, slider};
}

export function syncSliders() {
  for (const field of sliders.keys()) showSlider(field);
}

// A field left empty or half-typed must not post as 0 -- the server would
// answer 422 and the page would show an error for a value nobody chose.
export function numberOf(el) {
  const value = Number(el.value);
  return el.value === "" || !Number.isFinite(value) ? Number(el.defaultValue) : value;
}

// Split the controls the way /render wants them: page knobs under "page",
// size and text at the root, everything else under "tuning".
