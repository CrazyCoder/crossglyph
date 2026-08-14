import {form} from "./dom.js";
import {familyEntries, familyPicker} from "./family.js";
import {scheduleRender, undrawnCount} from "./render.js";
import {endProgress, showProgress, spellBytes, startProgress} from "./progress.js";
import {knobsDiffer, saveButton, saveKnobs, showSaveState} from "./save.js";

// --- export ---------------------------------------------------------------
// What a build contains and where it goes, which is the same .conf the knobs
// write: tune here, build here, and the family on the card is what you were
// looking at. Sizes, coverage and the two fallback families belong to the
// family; the output folder belongs to all.conf, since it is not a property
// of any one family.
export const exportForm = document.getElementById("export");
export const presetList = document.getElementById("presets");
export const outField = exportForm.elements.out;
export const builtNote = document.getElementById("built");
export let presetNames = [];

//: The ranges behind each preset, and the ones every build carries anyway.
//: Kept so the panel can answer "is this one already in that one" without a
//: round trip on every tick.
export const presetRanges = new Map();
export let baseRanges = [];

export function fillPresets(presets, base = []) {
  presetNames = presets.map(preset => preset.name);
  baseRanges = base;
  presetRanges.clear();
  presetList.replaceChildren(...presets.map(preset => {
    presetRanges.set(preset.name, preset.ranges || []);
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = preset.name;
    box.dataset.preset = preset.name;
    label.append(box, document.createTextNode(preset.label));
    if (preset.note) {
      const note = document.createElement("span");
      note.className = "note";
      note.textContent = preset.note;
      label.append(note);
    }
    return label;
  }));
}

export function presetBoxes() {
  return [...presetList.querySelectorAll("input")];
}

// Whether every range in `wanted` is already inside `have`. Ranges rather than
// codepoints: a preset is a handful of them, and CJK alone would be twenty
// thousand numbers to compare one at a time.
export function rangesCover(have, wanted) {
  return wanted.every(([low, high]) => {
    let at = low;
    while (at <= high) {
      const step = have.find(([from, to]) => from <= at && at <= to);
      if (!step) return false;
      at = step[1] + 1;
    }
    return true;
  });
}

//: A preset the reader ticked, as against one another tick already carries.
//: The box shows both the same way, so the set it is in has to be recorded
//: somewhere the display cannot overwrite.
export function chosenPresets() {
  return presetBoxes().filter(box => box.dataset.chosen === "yes")
                      .map(box => box.value);
}

// Show which ticks the other ticks have already made. `reading` is the
// converter's `default` and a good deal more, so ticking it settles four of
// these boxes -- and a row that says nothing about that reads as five separate
// things a build needs. Implied boxes are ticked and turned off: the state is
// true, and there is nothing to decide while what implies it is on.
//
// They are left out of what the panel posts and saves, so the config stays the
// short list the reader chose rather than growing every preset those imply.
export function syncPresetCoverage() {
  const chosen = chosenPresets();
  for (const box of presetBoxes()) {
    const own = box.dataset.chosen === "yes";
    const mine = presetRanges.get(box.value) || [];
    // Against the *others*, so a tick is never counted as covering itself.
    // That is what lets a chosen preset be told it adds nothing: a config
    // naming both `reading` and `symbols` is one tick doing no work, and the
    // row saying so is the whole point of this.
    const others = chosen.filter(name => name !== box.value);
    const covered = [...baseRanges];
    for (const name of others) covered.push(...(presetRanges.get(name) || []));
    // A preset with no ranges is one this build of the panel does not know,
    // and an empty set is inside everything. Left alone rather than locked.
    const inside = mine.length > 0 && others.length > 0
                   && rangesCover(covered, mine);

    // Carried and not chosen: on, and nothing to decide while what carries it
    // is on. Carried and chosen: still yours to untick, since you asked for it
    // and only you can take it back -- but said, so you can.
    box.disabled = inside && !own;
    box.checked = own || inside;
    box.parentElement.classList.toggle("implied", inside);
    box.title = inside
      ? `Already in ${others.join(", ")}, so this adds nothing`
      : "";
  }
}

// The config keeps a list of sizes, the panel shows a box per step. Four boxes
// because four is what the default ships and what the reader's Font Size list
// looks like out of the box -- but a family may carry more (a CJK one wants 8,
// 10 and 12 for the interface), and those go in a row that appears only when
// there are any, rather than being dropped by a control with nowhere to put
// them.
export const SIZE_FIELDS = ["size1", "size2", "size3", "size4"];
export const MOD_FIELDS = ["mod1", "mod2", "mod3", "mod4"];
export const moreRow = document.getElementById("more-row");
export const modMoreRow = document.getElementById("mod-more-row");
export const modName = document.getElementById("mod-name");
export const sizeNumbers = (text) => String(text).split(/[,\s]+/).filter(Boolean);

export function fillSizeBoxes(fields, text, spill) {
  const sizes = sizeNumbers(text);
  fields.forEach((name, index) => {
    exportForm.elements[name].value = sizes[index] ?? "";
  });
  if (spill) spill.value = sizes.slice(fields.length).join(" ");
}

// A blank box drops out rather than posting as nothing: three sizes is a config
// anyone may write by hand, so the panel has to be able to hold one.
export function joinSizeBoxes(fields, spill) {
  const boxes = fields.map(name => exportForm.elements[name].value);
  return [...boxes, spill ? spill.value : ""].flatMap(sizeNumbers).join(" ");
}

export function showSizes(settings) {
  const more = exportForm.elements.size_more;
  const modMore = exportForm.elements.mod_more;
  fillSizeBoxes(SIZE_FIELDS, settings.sizes, more);
  fillSizeBoxes(MOD_FIELDS, settings.sizes_mod || "", modMore);
  exportForm.elements.mod_suffix.value = settings.mod_suffix || "";
  // These rows are for what a config already carries: each appears when the
  // family loaded has sizes past its four boxes, and stays for as long as it
  // does -- neither may vanish under the cursor as the field is being cleared.
  moreRow.hidden = !more.value;
  modMoreRow.hidden = !modMore.value;
  showModState();
}

// The suffix only names something when there is a second family to name, and a
// field that cannot matter yet should not invite typing into it.
export function showModState() {
  const sizes = joinSizeBoxes(MOD_FIELDS, exportForm.elements.mod_more);
  const suffix = exportForm.elements.mod_suffix;
  suffix.disabled = !sizes;
  // Built on the name in the box rather than the one in the picker, so a
  // rename you have typed but not saved shows what both families would be
  // called -- they are one build, and the second is named after the first.
  const family = exportForm.elements.name.value.trim() || familyPicker.value;
  modName.textContent = sizes
    ? (family || "this family") + (suffix.value || "Mod")
    : "a second family";
}

// The config spells coverage as one comma-separated string, because that is
// what the converter takes; the panel spells it as ticks.
export function showExport(entry) {
  const settings = (entry && entry.export) || null;
  exportForm.hidden = !settings;
  if (!settings) return;
  exportForm.elements.name.value = settings.name;
  showSizes(settings);
  exportForm.elements.ranges.value = settings.ranges;
  exportForm.elements.fallbacks.checked = settings.fallbacks;
  // What the config names is what the reader chose; the rest of the ticks are
  // worked out from it, so a config that names `reading` alone still opens
  // with Default, Latin Extended and the others showing as carried.
  const ticked = new Set(settings.intervals.split(",").map(t => t.trim()));
  for (const box of presetBoxes()) {
    box.dataset.chosen = ticked.has(box.value) ? "yes" : "";
  }
  syncPresetCoverage();
  for (const field of ["fallback1", "fallback2"]) {
    exportForm.elements[field].value = settings[field] || "";
  }
}

export function exportSettings() {
  return {
    // Whatever was typed. The strip that makes it a filename is the server's,
    // and what it made of it comes back from the save, so the panel never has
    // to keep a second copy of that rule.
    name: exportForm.elements.name.value.trim(),
    sizes: joinSizeBoxes(SIZE_FIELDS, exportForm.elements.size_more),
    sizes_mod: joinSizeBoxes(MOD_FIELDS, exportForm.elements.mod_more),
    mod_suffix: exportForm.elements.mod_suffix.value.trim(),
    // Only what was chosen. A preset another one already carries is shown
    // ticked, and writing it down as well would grow the config by every
    // preset the chosen ones imply, which is the list this is trying to spare
    // anybody reading it.
    intervals: chosenPresets().join(","),
    // Trimmed, because this is compared against what the config says to decide
    // whether there is anything to save: a trailing space is not an edit.
    ranges: exportForm.elements.ranges.value.trim(),
    fallbacks: exportForm.elements.fallbacks.checked,
    fallback1: exportForm.elements.fallback1.value,
    fallback2: exportForm.elements.fallback2.value,
  };
}

// A fallback is a family in this same folder, minus the one being built --
// falling back to yourself fills nothing.
export function fillFallbackPickers() {
  for (const field of ["fallback1", "fallback2"]) {
    const picker = exportForm.elements[field];
    const chosen = picker.value;
    picker.replaceChildren(new Option("none", ""));
    for (const name of familyEntries.keys()) {
      if (name && name !== familyPicker.value) picker.add(new Option(name, name));
    }
    picker.value = chosen;
  }
}

// A line of JSON per step, read as it arrives. A build is minutes when the
// fallbacks are on, and a button that says "building" the whole time is
// indistinguishable from one that has hung.
export function showStep(step) {
  if (step.event === "plan") {
    // The bar takes the counting from here; the note is left for the outcome,
    // and a run with nothing to do is one.
    if (step.total) {
      builtNote.textContent = "";
      showProgress(0, step.total, "");
    } else {
      builtNote.textContent = "everything is already current";
      endProgress();
    }
  } else if (step.event === "size") {
    showProgress(step.done, step.total, `${step.family} ${step.size}`);
  } else if (step.event === "failed") {
    // One size of many, and the build carries on: the bar keeps running and
    // the note says which one went wrong.
    builtNote.textContent = `${step.family} ${step.size}: ${step.error}`;
  } else if (step.event === "error") {
    endProgress();
    builtNote.textContent = step.error;
  } else if (step.event === "done") {
    endProgress();
    const count = (key) =>
      step.families.reduce((total, one) => total + one[key].length, 0);
    const failed = count("failed");
    // A family no config produces any more takes its whole directory with it,
    // and that is worth a word: it is the one thing a build does that removes
    // something you might still have been expecting on the card.
    const gone = (step.removed || []).length;
    // What it cost, beside what it did: these go on a card with a fixed amount
    // of room, and a build is the moment to know. Only when something was
    // built -- "0 built (0 B)" says nothing twice.
    const made = count("built");
    const kept = count("skipped");
    const size = made && step.bytes ? ` (${spellBytes(step.bytes)})` : "";
    const had = kept && step.current_bytes
      ? ` (${spellBytes(step.current_bytes)})` : "";
    builtNote.textContent =
      `${made} built${size}, ${kept} already current${had}`
      + (failed ? `, ${failed} failed` : "")
      + (gone ? `, removed ${step.removed.join(", ")}` : "")
      + ` → ${step.out}`;
  }
}

// Both buttons are out while one of them is working. A build is minutes with
// the fallbacks on, the server takes them one at a time, and a second press
// would only queue a run behind the one whose progress is on screen.
export const buildButtons = [document.getElementById("build"),
                     document.getElementById("build-all")];

// Shift is what this page already means by "more": ten at a time on a stepper,
// and here a build that ignores what is already current. A rebuild is minutes
// and is wanted rarely, so it is a modifier on the button that builds rather
// than a third button, or a tick sitting in the panel saying nothing all day.
export function forcedLabel(plain) { return plain.replace("Build", "Rebuild"); }

// A modifier nobody can see is a feature nobody finds, so the buttons say what
// they will do for as long as it is held.
export const plainLabels = buildButtons.map(button => button.textContent);
export function showForceState(held) {
  buildButtons.forEach((button, at) => {
    button.textContent = held ? forcedLabel(plainLabels[at]) : plainLabels[at];
  });
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Shift") showForceState(true);
});
document.addEventListener("keyup", (event) => {
  if (event.key === "Shift") showForceState(false);
});

export async function buildFamilies(family, force = false) {
  const label = family || "every family";
  for (const button of buildButtons) button.disabled = true;
  try {
    // The .conf is the only channel a build has: the server re-reads it and
    // rebuilds the sizes whose inputs changed. A coverage tick or a knob that
    // is only on the page is therefore not in that comparison, so the build
    // finds everything current and says so -- which reads as "your change did
    // nothing" when it means "your change was never seen". Write it first.
    startProgress(`${force ? "rebuilding" : "planning"} ${label}…`);
    builtNote.textContent = "";
    if (!saveButton.hidden && knobsDiffer() && !(await saveKnobs())) {
      builtNote.textContent = `not built: ${label} could not be saved`;
      return;
    }
    await streamInto("/build", {family: family, force: force},
                     showStep, builtNote);
  } finally {
    // Whatever happened -- a dropped connection, a line that would not parse --
    // the buttons come back, or the panel is dead until a reload. The bar
    // goes with them: a dropped connection would otherwise leave it sitting at
    // whatever fraction it had reached, saying a run is still going.
    endProgress();
    for (const button of buildButtons) button.disabled = false;
    // The key may well have been let go while the buttons were out, and a
    // keyup on a disabled button is one nobody hears.
    showForceState(false);
  }
}

// Both long jobs answer a line of JSON at a time rather than one reply at the
// end, so both read it the same way. A chunk can split a line anywhere, so
// whatever arrives without its newline is held for the next one.
// Post, and read the answer into `onStep` a line at a time. Both long jobs
// answer that way, and both can fail in the same two ways before the first
// line arrives: no answer at all, and a refusal with a sentence in it. `note`
// is where either is said, and false means the run never started.
export async function streamInto(url, body, onStep, note) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify(body)});
  } catch (error) {
    note.textContent = String(error);
    return false;
  }
  if (!response.ok) { note.textContent = await response.text(); return false; }
  await readSteps(response, onStep);
  return true;
}

export async function readSteps(response, onStep) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    pending += decoder.decode(value, {stream: true});
    const lines = pending.split("\n");
    pending = lines.pop();
    for (const line of lines) if (line.trim()) onStep(JSON.parse(line));
  }
}

// Editing any of it offers a save, the same as a knob does. The output folder
// is the exception: it is all.conf's and saves itself below.
export const FALLBACK_FIELDS = new Set(["fallbacks", "fallback1", "fallback2"]);

// One field of the panel changed, however it changed. A name rather than an
// event, so the fetch can go through the same path a tick of the box goes
// through instead of arriving at the same state by another road.
export function exportEdited(field) {
  if (field === outField) return;
  // A tick is a choice; what it implies is worked out from it. Recorded before
  // anything reads the row, since the boxes cannot tell the two apart.
  if (field.dataset && field.dataset.preset) {
    field.dataset.chosen = field.checked ? "yes" : "";
    syncPresetCoverage();
  }
  // Typing a second family's first size is what turns its suffix on.
  showModState();
  showSaveState();
  // The fallbacks reach the page as well as the build, so changing which face
  // fills for the family redraws it. A coverage tick only matters while the
  // bundled set is on, since that is the list it decides.
  if (FALLBACK_FIELDS.has(field.name) ||
      (field.dataset.preset && exportForm.elements.fallbacks.checked)) {
    scheduleRender();
  }
}

exportForm.addEventListener("input", (event) => exportEdited(event.target));

// The faces are not vendored: they are large, unmodified and OFL, so they are
// fetched once into the font source folder. The offer only appears when they
// are not already somewhere -- a checkout beside the repo counts.
export const fetchButton = document.getElementById("fetch");
export const fetchNote = document.getElementById("fetched");
export const haveFallbacks = document.getElementById("have-fallbacks");

export function showFallbackState(where) {
  fetchButton.hidden = Boolean(where);
  // The last two segments: the whole path is most of a line and says
  // little the tail does not -- once they are fetched it is the font
  // folder and "fallbacks", and before that the checkout's own. The
  // whole of it stays in the title.
  const tail = where ? where.split(/[\\/]/).slice(-2).join("\\") : "";
  haveFallbacks.textContent = where ? `from ${tail}` : "not fetched yet";
  haveFallbacks.title = where || "";
}

export function showFetchStep(step) {
  if (step.event === "error") { fetchNote.textContent = step.error; return; }
  // Nothing to download is worth saying: the button looks identical whether it
  // did twenty megabytes or found them already there.
  if (step.event === "plan" && !step.files) {
    fetchNote.textContent = "already fetched";
    return;
  }
  if (step.event === "done") {
    fetchNote.textContent = `${step.faces} faces`;
    showFallbackState(step.where);
    // Fetching the faces is only half of it: the box beside them is what puts
    // them on the page and in the build, and a download that left the page
    // exactly as blank as before is a button that did nothing you can see.
    // Only when something on the page needed them, and by the same path a tick
    // takes, so the panel offers to save it like any other change. The box
    // moves where you can see it, which is what keeps this from being a
    // setting changed behind your back.
    const box = exportForm.elements.fallbacks;
    if (undrawnCount && box && !box.checked) {
      box.checked = true;
      exportEdited(box);
      return;                     // exportEdited redraws for this field
    }
    // The page can draw more than it could a moment ago, which is the whole
    // reason anyone pressed this.
    scheduleRender();
    return;
  }
  if (step.event === "start" || step.event === "step") {
    showProgress(step.got, step.bytes, step.name, spellBytes);
  }
}

export async function fetchFallbacks() {
  // Out for the duration. It is a 20 MB download with a CJK face in it, and a
  // button that still looks pressable is one people press again.
  fetchButton.disabled = true;
  fetchNote.textContent = "";
  startProgress("asking for the fallback faces…");
  try {
    // The coverage says which scripts a build wants; the text says what this
    // page cannot draw. Either is a reason to bring a CJK face, and the second
    // is what makes one press enough after the page has said characters are
    // missing.
    await streamInto("/fallbacks",
                     {intervals: exportSettings().intervals,
                      text: form.elements.text.value},
                     showFetchStep, fetchNote);
  } finally {
    // Whatever happened, the button comes back and the bar goes: a dropped
    // connection would otherwise leave both saying a download is still running.
    endProgress();
    fetchButton.disabled = false;
  }
}

//: Wired by the entry point rather than on import: familyPicker belongs to
//: family.js, and a module body can run while a module it imports is still
//: evaluating. Build takes what the picker is on; Build all takes nothing and
//: means every family in the workspace.
export function wireBuildButtons() {
  fetchButton.addEventListener("click", fetchFallbacks);
  buildButtons[0].addEventListener(
    "click", (event) => buildFamilies(familyPicker.value, event.shiftKey));
  buildButtons[1].addEventListener(
    "click", (event) => buildFamilies("", event.shiftKey));
}

// The output folder is all.conf's, so it saves on its own rather than with a
// family -- and on leaving the field, since there is nothing else to press.
outField.addEventListener("change", async () => {
  const response = await fetch("/out", {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({out: outField.value})});
  if (response.ok) {
    const result = await response.json();
    builtNote.textContent = `builds go to ${result.out}`;
  } else {
    builtNote.textContent = await response.text();
  }
});
