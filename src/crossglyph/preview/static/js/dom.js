export const form = document.getElementById("knobs");
export const img = document.getElementById("page");
export const status = document.getElementById("status");
export const lineHeightAuto = document.getElementById("lh-auto");
// Which specimen is in the box. Chrome rather than a knob, so it carries no
// name and the form sweep never posts it -- what reaches /render is the text
// itself, whoever chose it.
export const samplePicker = document.getElementById("sample");

// The field means nothing while the font's own height is in use, so grey it
// and its steppers out rather than showing a number that is not being applied.
// `disabled` is an attribute rather than a value, so restoring defaults does
// not restore it -- both the toggle and the resets come through here.
export function syncLineHeight() {
  const off = lineHeightAuto.checked;
  form.elements.line_height.disabled = off;
  for (const control of form.querySelectorAll(
      '[data-for="line_height"], [data-slider-for="line_height"]')) {
    control.disabled = off;
  }
}
lineHeightAuto.addEventListener("change", syncLineHeight);

// The same again, and for the same reason. A language only says which patterns
// hyphenate; with the switch under it off, nothing does, and turning the knob
// draws the identical page. Greyed, the row says so before it is turned.
export function syncHyphenation() {
  form.elements.language.disabled = !form.elements.hyphenation.checked;
}
form.elements.hyphenation.addEventListener("change", syncHyphenation);

//: Why a knob is out of reach, when it is the font rather than another knob
//: holding it there. Keyed by control name, as /defaults reports them.
export const FEATURE_REASON = {
  ligatures: "This family carries no ligature rules, so there is nothing for "
    + "the switch to turn off.",
  figures: "This family has no proportional figures, so every setting here "
    + "draws the same digits.",
};

// Knobs the font itself cannot answer. Turning one of these on a face with no
// such feature draws the identical page, so the row says so before it is
// turned rather than leaving somebody to wonder what they are looking for.
export function syncFeatures(features) {
  for (const [name, why] of Object.entries(FEATURE_REASON)) {
    const el = form.elements[name];
    if (!el) continue;
    // A family the app was started on as a bare file reports nothing, and a
    // knob is only ever greyed on an answer.
    const missing = features ? features[name] === false : false;
    el.disabled = missing;
    el.title = missing ? why : "";
  }
}
