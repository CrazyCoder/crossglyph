import {form, img, lineHeightAuto, status} from "./dom.js";
import {exportForm, exportSettings} from "./export.js";
import {familyPicker} from "./family.js";
import {numberOf, showSlider} from "./knobs.js";
import {savePage} from "./remember.js";
import {refreshReverts, stashed} from "./reverts.js";
import {saveText} from "./text.js";
import {axisSettings} from "./variable.js";

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
  const settings = exportForm.hidden ? null : exportSettings();
  if (settings) {
    out.fallbacks = settings.fallbacks;
    out.fallback1 = settings.fallback1;
    out.fallback2 = settings.fallback2;
    // Which coverage the build would carry, which is what decides whether the
    // 15.7 MB CJK face is one of the bundled ones. The preview still
    // rasterizes the text and nothing else.
    out.intervals = settings.intervals;
  }
  return out;
}

// Draw now. Only two things call this: the first paint, and a family switch,
// which are one-off and deliberate. Everything driven by a control calls
// scheduleRender instead -- see below.
// Which request is the current one, what it drew, and the timer that
// coalesces the ones behind it.
let timer = null, latest = 0, url = null, inFlight = null;

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

// 503 is a state of the workspace, 422 a setting the converter would not take.
// Both are things to do something about, so each says which it is.
export function failureHeadline(status) {
  if (status === 503) return "The page cannot be drawn yet.";
  if (status === 422) return "That setting was refused.";
  return `The page could not be drawn (${status}).`;
}

export async function renderNow() {
  const mine = ++latest;
  const started = performance.now();
  // The core renders one page at a time, so a held stepper would otherwise
  // queue a render per step and show them minutes later. Drop the previous
  // request instead: nobody is going to look at it.
  if (inFlight) inFlight.abort();
  inFlight = new AbortController();
  let response;
  try {
    response = await fetch("/render", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify(body()), signal: inFlight.signal});
  } catch (error) {
    // An abort is this page's own doing: a newer render replaced this one, and
    // it is about to paint.
    if (error.name === "AbortError") return;
    showPageError("The preview server is not answering.",
                  "It may have stopped. Start it again, then press Try again.");
    status.textContent = "no answer";
    return;
  }
  // A slow request that lost the race must not paint over a newer page.
  if (mine !== latest) return;
  if (!response.ok) {
    showPageError(failureHeadline(response.status), await failureText(response));
    status.textContent = `${response.status}`;
    return;
  }
  const next = URL.createObjectURL(await response.blob());
  if (url) URL.revokeObjectURL(url);
  img.src = url = next;
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
  if (el.name === "text") saveText();
  // Typing goes straight into the field, so without this the slider sits
  // wherever it was until the field loses focus and `change` finally fires.
  if (el.type === "number" && el.value !== "") showSlider(el);
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
  knobChanged(event.target);
}
form.addEventListener("input", onInput);
// The text box is a control of this form by `form="knobs"` rather than by
// containment -- it sits under the specimen, in the middle column. An event
// bubbles up the DOM and not to the form a control belongs to, so without this
// line the form's listener never hears it and typing draws nothing.
form.elements.text.addEventListener("input", onInput);

// Two resets rather than one. The page knobs are the reader's device settings,
// which you keep while turning font knobs -- resetting both together is almost
// never what is wanted, since it throws away the configuration you are trying
// to preview against.
//
// A native type="reset" restores every control at once, so scoping it means
// doing the restore here. defaultValue / defaultChecked / defaultSelected are
// the DOM's own record of what the markup declared, so there is still no
// second copy of the defaults to drift out of sync.
