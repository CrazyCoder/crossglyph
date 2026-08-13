export const form = document.getElementById("knobs");
export const img = document.getElementById("page");
export const status = document.getElementById("status");
export const lineHeightAuto = document.getElementById("lh-auto");

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
