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

// Why stem darkening would do nothing as the panel currently stands, or "".
//
// Not a property of the font alone, which is why it is not in the table above.
// FreeType darkens in two engines -- the Adobe CF2 interpreter that draws CFF
// and Type 1 faces, and the auto-hinter -- and each puts a condition of its own
// on top: CF2 darkens a scaled load, the auto-hinter darkens at a light target.
// So the hinting row two above decides this as much as the face does. `auto`
// fails both at once, since it targets normal hinting and the auto-hinter
// reloads the glyph unscaled. Measured over 132 faces on FreeType 2.13.2.
//
// Only those two are said. A CFF face whose stems fall where the darkening
// curve rounds to nothing is unmoved as well, and nothing short of rasterizing
// both ways could know that; a face FreeType calls tricky never reaches the
// auto-hinter, so `light` does nothing for it either. Both are left alone.
// Greying is a claim, and the one thing this must never do is make it about a
// knob that works.
export function darkeningReason(outlines, hinting) {
  if (hinting === "auto") {
    return "FreeType darkens at a light target or on a scaled load, and auto "
      + "hinting is neither, so the switch does nothing here.";
  }
  if (outlines === "truetype" && hinting !== "light") {
    return "These are TrueType outlines, which FreeType darkens only under "
      + "light hinting.";
  }
  return "";
}

//: What the family showing can answer. Kept, because the rule above reads a
//: knob as well as the font, so the row has to be worked out again whenever
//: that knob moves and there is no family to hand then.
let supported = null;
let outlines = "";

// The family changed. Everything a knob can be greyed on is a property of it.
export function showFeatures(entry) {
  supported = (entry && entry.features) || null;
  outlines = (entry && entry.outlines) || "";
  syncFeatures();
}

// Knobs the font cannot answer. Turning one of these on a face without the
// feature draws the identical page, so the row says so before it is turned
// rather than leaving somebody to wonder what they are looking for.
export function syncFeatures() {
  for (const [name, why] of Object.entries(FEATURE_REASON)) {
    const el = form.elements[name];
    if (!el) continue;
    // A family the app was started on as a bare file reports nothing, and a
    // knob is only ever greyed on an answer.
    const missing = supported ? supported[name] === false : false;
    el.disabled = missing;
    el.title = missing ? why : "";
  }
  const darkening = form.elements.stem_darkening;
  const hinting = form.elements.hinting;
  if (!darkening || !hinting) return;
  const why = darkeningReason(outlines, hinting.value);
  darkening.disabled = Boolean(why);
  darkening.title = why;
}
form.elements.hinting.addEventListener("change", syncFeatures);
