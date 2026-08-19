import {form, lineHeightAuto, status} from "./dom.js";
import {showRenderedPage} from "./device.js";
import {exportForm, exportSettings, fetchButton, presetBoxes} from "./export.js";
import {familyPicker} from "./family.js";
import {numberOf, showSlider} from "./knobs.js";
import {savePage, saveSize} from "./remember.js";
import {refreshReverts, stashed} from "./reverts.js";
import {languageChosen, typedInBox} from "./text.js";
import {axisSettings, refreshAxisReverts} from "./variable.js";

export function body() {
  const out = {tuning: {}, page: {}};
  for (const el of form.elements) {
    if (!el.name) continue;
    const value = el.type === "checkbox" ? el.checked
                : el.type === "number" ? numberOf(el) : el.value;
    const group = el.dataset.group ?? "tuning";
    if (group === "axes") continue;      // gathered by axisSettings() below
    if (group === "root") out[el.name] = value; else out[group][el.name] = value;
  }
  // Which instance of a variable font each slot is drawn at. Empty for a
  // static family, which is what leaves the file's own faces alone.
  out.axes = axisSettings();
  // The picker is chrome rather than a knob, so it is named here rather than
  // swept up with the form. Empty means the family the app was started on.
  out.family = familyPicker.value;
  // An empty box means "use the server's sample", not "render nothing" --
  // absent falls back to SAMPLE_TEXT, "" would draw a blank page.
  if (!out.text) delete out.text;
  // Absent line_height means "whatever the font's own hhea says", which is not
  // a number any field position can stand for.
  if (lineHeightAuto.checked) delete out.tuning.line_height;
  // The fallbacks as the export panel currently shows them, not as the config
  // has them: ticking the box is a change you want to see. They reach the
  // build only for a codepoint this family lacks, so on a page that is all in
  // the family they cost nothing and change nothing.
  // The panel is hidden exactly when this family has no config to read one
  // from, which is also when there is no coverage to hold the page to. So the
  // one guard answers both: send what it shows, or say nothing and let the
  // server draw the text as it comes.
  const settings = exportForm.hidden ? null : exportSettings();
  if (settings) {
    out.fallbacks = settings.fallbacks;
    out.fallback1 = settings.fallback1;
    out.fallback2 = settings.fallback2;
    // Coverage decides what the page draws and not only what a build writes:
    // the preview rasterizes the text less anything this coverage would leave
    // out, so a family cannot look finished here and reach the device
    // unreadable.
    out.intervals = settings.intervals;
    out.ranges = settings.ranges;
  }
  return out;
}

// Draw now. Only two things call this: the first paint, and a family switch,
// which are one-off and deliberate. Everything driven by a control calls
// scheduleRender instead -- see below.
// Which request is the current one, and the timer that coalesces the ones
// behind it.
let timer = null, latest = 0, inFlight = null;

export const pageError = document.getElementById("page-error");

// What a failed render says, over the sheet. `what` is the sentence, `why` the
// server's own words when it had any.
export function showPageError(what, why) {
  pageError.querySelector(".what").textContent = what;
  pageError.querySelector(".why").textContent = why || "";
  pageError.hidden = false;
}

// FastAPI answers {"detail": "..."} and everything else answers text. The
// reader wants the sentence either way, not the envelope it came in.
export async function failureText(response) {
  const raw = await response.text();
  try {
    const parsed = JSON.parse(raw);
    return typeof parsed.detail === "string" ? parsed.detail : raw;
  } catch { return raw; }
}

// What each kind of failed render is called, keyed by the x-fault the server
// sends with it. The status alone cannot say: a knob the converter would not
// take, a family whose files have moved and a font file nobody can read all
// arrive as 422, and one headline over the three names the wrong thing twice.
// The sentence under it is the server's, and says which file or which knob.
const FAULTS = {
  font: "A font file could not be read.",
  family: "That family is no longer in the font folder.",
  config: "A font config file was refused.",
  converter: "The converter would not build this font.",
  setting: "That setting was refused.",
};

// 503 is a state of the workspace, 422 something about this request. A fault
// the page does not know the name of falls back to the status, which is what
// an older server and every other endpoint give it.
export function failureHeadline(status, fault) {
  // hasOwn, not a plain lookup: every object inherits `constructor` and
  // `toString`, and a header naming one of those would put a function where
  // the headline goes.
  if (fault && Object.hasOwn(FAULTS, fault)) return FAULTS[fault];
  if (status === 503) return "The page cannot be drawn yet.";
  if (status === 422) return "That setting was refused.";
  return `The page could not be drawn (${status}).`;
}

export const undrawnNote = document.getElementById("undrawn");

//: How many characters the last page could not draw. The fetch reads it to
//: know whether the faces it just brought are ones this page was waiting for.
export let undrawnCount = 0;

// What the page could not draw, said under the box the text came from. The
// count arrives on the render itself, because it is a fact about this page and
// not about the folder.
export function showUndrawn(count) {
  undrawnCount = count;
  // Whichever move is the one left to make, marked the way a coverage tick is.
  // The box while it is off; once it is on, the faces still have to be here,
  // and Fetch shows itself exactly when they are not. With it on and the faces
  // present there is nothing to mark: the family and its fallbacks between them
  // genuinely have no glyph, and no control on this panel changes that.
  const box = exportForm.elements.fallbacks;
  const wanting = count > 0;
  if (box && box.parentElement) {
    box.parentElement.classList.toggle("needed", wanting && !box.checked);
  }
  if (fetchButton) {
    fetchButton.classList.toggle(
      "needed", wanting && Boolean(box && box.checked) && !fetchButton.hidden);
  }
  undrawnNote.hidden = !count;
  if (!count) return;
  // The move that is actually left, which is the one being marked above. The
  // bundled set is two conditions and either can be the missing one: the faces
  // have to be here, and the box has to be on for the page and the build to
  // use them. Naming a family in fallback 1 answers all three, and is the only
  // answer left once the bundled faces are here and have no glyph either, so
  // it is said every time rather than only at the end.
  const named = "or name a family that has them in fallback 1";
  const move = !(box && box.checked)
    ? `Under Export, turn on bundled fallback faces, ${named}.`
    : fetchButton && !fetchButton.hidden
    ? `Press Fetch under Export to bring the bundled faces down, ${named}.`
    : `The bundled faces are on and have none either, so this needs a family `
      + `that has them in fallback 1.`;
  undrawnNote.textContent =
    `${count} character${count === 1 ? " has" : "s have"} no glyph in this `
    + `family or its fallback faces, so the page is blank where `
    + `${count === 1 ? "it is" : "they are"}. ${move}`;
}

export const uncoveredNote = document.getElementById("uncovered");

// What this coverage would leave out of the built font. A different fault from
// the one above and a different answer: the family has the glyph, the build
// would not carry it, and the fix is a tick rather than a download. Named
// rather than left to be worked out, and not ticked here: coverage decides
// what a build writes, so it is not a setting to change behind somebody's
// back.
export function showUncovered(count, presets) {
  const named = new Set((presets || "").split(",").filter(Boolean));
  // The boxes themselves, so the answer is where the answer is applied. Only
  // "implied" is toggled by syncPresetCoverage, so this survives a redraw of
  // the row and clears itself the moment the page can draw everything.
  for (const box of presetBoxes()) {
    box.parentElement.classList.toggle("needed", count > 0 && named.has(box.value));
  }
  uncoveredNote.hidden = !count;
  if (!count) return;
  const where = named.size
    ? `Tick ${[...named].join(" and ")} under Export to carry ${
        count === 1 ? "it" : "them"}.`
    : "No coverage preset carries them, so this needs a range under Export.";
  uncoveredNote.textContent =
    `${count} character${count === 1 ? " is" : "s are"} outside the coverage `
    + `you have ticked, so the page is blank where ${
        count === 1 ? "it is" : "they are"} and the built font would be too. `
    + where;
}

export async function renderNow() {
  const mine = ++latest;
  const started = performance.now();
  // The core renders one page at a time, so a held stepper would otherwise
  // queue a render per step and show them minutes later. Drop the previous
  // request instead: nobody is going to look at it.
  if (inFlight) inFlight.abort();
  inFlight = new AbortController();
  let response, payload;
  try {
    response = await fetch("/render", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify(body()), signal: inFlight.signal});
    if (mine !== latest) return;
    // Abort covers the body as well as the headers. A superseded response can
    // be interrupted in either read, and neither is an error worth reporting.
    payload = response.ok ? await response.blob() : await failureText(response);
  } catch (error) {
    // An abort is this page's own doing: a newer render replaced this one, and
    // it is about to paint.
    if (error.name === "AbortError" || mine !== latest) return;
    showPageError("The preview server is not answering.",
                  "It may have stopped. Start it again, then press Try again.");
    status.textContent = "no answer";
    return;
  }
  // Body reads can finish after a newer response. Stop before touching the
  // shared blob URL or image: either would replace state the newer page owns.
  if (mine !== latest) return;
  if (!response.ok) {
    showPageError(failureHeadline(response.status,
                                  response.headers.get("x-fault")), payload);
    status.textContent = `${response.status}`;
    return;
  }
  showUndrawn(Number(response.headers.get("x-undrawn")) || 0);
  showUncovered(Number(response.headers.get("x-uncovered")) || 0,
                response.headers.get("x-coverage-fix"));
  // Decoded straight from the response bytes, off the DOM: no element, no
  // object URL, no load or decode() state whose lifetime a later render has
  // to manage. The canvas keeps the previous page until this one is ready.
  let bitmap;
  try {
    bitmap = await createImageBitmap(payload);
  } catch (error) {
    if (mine !== latest) return;
    showPageError("The page could not be shown.", String(error));
    status.textContent = "bad image";
    return;
  }
  if (mine !== latest) {
    if (typeof bitmap.close === "function") bitmap.close();
    return;
  }
  showRenderedPage(bitmap);
  pageError.hidden = true;
  status.textContent = `${Math.round(performance.now() - started)} ms`;
}

// The one way a control asks for a page. Coalescing is not a nicety here:
// the core draws one page at a time and a slider fires an event per pixel,
// so an un-coalesced path queues a render per pixel and the page falls
// minutes behind the knob. Anything that reacts to a control goes through
// this, and nothing calls renderNow directly.
export function scheduleRender() {
  clearTimeout(timer);
  timer = setTimeout(renderNow, 150);
}

export function knobChanged(el) {
  if (el.dataset.group === "page") savePage();
  // A comparison is a temporary look, not a new choice to restore next visit.
  if (el.name === "size" && !stashed.has("size")) saveSize();
  if (el.name === "text") typedInBox();
  // Typing goes straight into the field, so without this the slider sits
  // wherever it was until the field loses focus and `change` finally fires.
  if (el.type === "number" && el.value !== "") showSlider(el);
  if (el.dataset.group === "axes") refreshAxisReverts();
  refreshReverts();
  scheduleRender();
}

// Every control in the form, named or not. "Use the font's own" has an id and
// no name, so guarding on the name left it re-enabling the field without ever
// asking for a page -- you could turn it back on and watch nothing happen.
export function onInput(event) {
  // Editing a knob yourself replaces whatever its arrow had set aside: from
  // here the comparison is against the default, not against a value you have
  // already moved on from.
  const name = event.target.name || event.target.dataset.sliderFor;
  if (name) stashed.delete(name);
  // While your own text is showing, which language to hyphenate it as is a
  // fact about that text and has to come back with it. Recorded from here
  // rather than from knobChanged, which the arrow also reaches: setting the
  // row aside to compare it is not a choice about your text, and writing the
  // compared value down would hand it back the next time you returned.
  if (event.target.name === "language") languageChosen();
  knobChanged(event.target);
}
//: Wired by the entry point rather than on import: `form` belongs to dom.js,
//: and a module body can run while a module it imports is still evaluating.
export function wireRender() {
  form.addEventListener("input", onInput);
  // The text box is a control of this form by `form="knobs"` rather than by
  // containment -- it sits under the specimen, in the middle column. An event
  // bubbles up the DOM and not to the form a control belongs to, so without
  // this line the form's listener never hears it and typing draws nothing.
  form.elements.text.addEventListener("input", onInput);
}

// Two resets rather than one. The page knobs are the reader's device settings,
// which you keep while turning font knobs -- resetting both together is almost
// never what is wanted, since it throws away the configuration you are trying
// to preview against.
//
// A native type="reset" restores every control at once, so scoping it means
// doing the restore here. defaultValue / defaultChecked / defaultSelected are
// the DOM's own record of what the markup declared, so there is still no
// second copy of the defaults to drift out of sync.
