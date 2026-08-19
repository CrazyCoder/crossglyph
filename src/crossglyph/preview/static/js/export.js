import {form} from "./dom.js";
import {familyEntries, familyPicker} from "./family.js";
import {setField} from "./knobs.js";
import {scheduleRender, undrawnCount} from "./render.js";
import {progressBar, spellBytes} from "./progress.js";
import {knobsDiffer, saveButton, saveKnobs, savedNote,
        showSaveState} from "./save.js";

// --- export ---------------------------------------------------------------
// What a build contains and where it goes, which is the same .conf the knobs
// write: tune here, build here, and the family on the card is what you were
// looking at. The name, the sizes, the coverage and the two fallback families
// belong to the family; the output folder belongs to all.conf, since it is not
// a property of any one family.
export const exportForm = document.getElementById("export");
export const presetList = document.getElementById("presets");
export const outField = exportForm.elements.out;
export const builtNote = document.getElementById("built");
// The panel's own bar, in the foot of the panel rather than in the card: a
// build is the one thing here that changes height while you watch it, and the
// foot is where it can. The island under the specimen has another, for the
// update, and neither run can be told anything by the other's clock. The mark
// is on the tab that opens this panel, for the widths where the panel is
// behind one: a build is minutes, and it must not be minutes of nothing said
// because the reader went back to the knobs.
//
// The foot itself is handed over as the row -- the bar and the line are parts
// of it, and it is what the tab takes out of the document -- and kept, since
// its rule is the divider under the buttons whether or not anything is
// running. See progressBar.
const progress = progressBar(document.getElementById("buildbar"),
                             document.getElementById("tab-busy"),
                             {keep: true});
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
// What the fold says about itself: sizes are set in there. The panel works
// that out for the suffix field anyway, so it is the one that says so.
export const modDot = document.getElementById("mod-dot");
export const sizeNumbers = (text) => String(text).split(/[,\s]+/).filter(Boolean);

//: The step the size knob moves in, and the range it covers. These boxes hold
//: sizes that are meant to have been looked at first, so they take what that
//: knob can reach and nothing between its steps: a size you cannot preview is
//: a size you cannot check before it ships.
export const SIZE_STEP = 0.25, SIZE_MIN = 6, SIZE_MAX = 40;

// One size, as this panel will hold it: snapped to the quarter point and held
// inside the previewable range.
//
// A comma is a decimal point here rather than a separator. Each of these boxes
// holds one size, so `13,25` in one of them can only mean 13.25 -- and that is
// what a keyboard laid out for Russian or German types. The config's own
// separator is comma-or-space, where the same string means two sizes, so the
// panel is the only place that can tell them apart.
//
// Anything that is not a number is handed back as typed. The save runs it
// through the converter's own parser and names the problem, which is a better
// answer than a box that empties itself.
export function snapSize(text) {
  const typed = String(text).trim();
  if (!typed) return "";
  const value = Number(typed.replace(",", "."));
  if (!Number.isFinite(value)) return typed;
  const held = Math.min(SIZE_MAX, Math.max(
    SIZE_MIN, Math.round(value / SIZE_STEP) * SIZE_STEP));
  // toFixed rounds off the arithmetic, String(Number(...)) drops the padding
  // it adds: a quarter-point box should read 13.25 and 14, not 14.00.
  return String(Number(held.toFixed(2)));
}

// The spill field, which is a list rather than one size: comma keeps meaning
// "and" in there, and every entry snaps the same way.
export function snapSizeList(text) {
  return sizeNumbers(text).map(snapSize).join(" ");
}

//: The whole number a size ships under, which is what the filename carries and
//: what the device lists. Half up, matching fontconf.size_label -- the device
//: parses the label out of the filename with strtol into a uint8_t, so a
//: fractional size cannot be named there at all.
export const sizeLabel = (size) => Math.floor(size + 0.5);

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
  showShipsAs();
}

// What this family is called once it is built. The name in the box rather than
// the one in the picker, so a rename you have typed but not saved shows what
// the build would produce.
export function familyLabel() {
  return exportForm.elements.name.value.trim() || familyPicker.value
         || "this family";
}

// What the second family's name ends with, as a save would write it: the panel
// posts a trimmed suffix and an empty one means the default. One function, so
// the heading and the note under the boxes cannot name two different families.
export const modSuffix = () =>
  exportForm.elements.mod_suffix.value.trim() || "Mod";

// The suffix only names something when there is a second family to name, and a
// field that cannot matter yet should not invite typing into it.
export function showModState() {
  const sizes = joinSizeBoxes(MOD_FIELDS, exportForm.elements.mod_more);
  const suffix = exportForm.elements.mod_suffix;
  suffix.disabled = !sizes;
  // They are one build, and the second family is named after the first.
  modName.textContent = sizes ? familyLabel() + modSuffix() : "a second family";
  modDot.hidden = !sizes;
}

export const shipsAs = document.getElementById("ships-as");
export const modShipsAs = document.getElementById("mod-ships-as");

// What a fractional size will be called on the card. The boxes cannot say it
// for themselves: 13.25 is rasterized at 13.25 and shipped as `Family_13`,
// because the device parses the size out of the filename and cannot hold a
// fraction there. Without this the first time anybody learns which entry in the
// Font Size list is which is on the device.
//
// It also puts the collision in front of the person while they are typing.
// Quarter points make one easy -- 13.5 and 13.75 are both 14 -- and the save
// refuses it, so the only other place to find out is a press of Save that does
// nothing.
export function spellShipsAs(note, text, family) {
  const sizes = sizeNumbers(text).map(Number).filter(Number.isFinite);
  const bunched = new Map();
  for (const size of sizes) {
    const label = sizeLabel(size);
    bunched.set(label, [...(bunched.get(label) || []), size]);
  }
  const clash = [...bunched.entries()].find(([, group]) => group.length > 1);
  const fractional = sizes.filter(size => sizeLabel(size) !== size);
  note.classList.toggle("warn", Boolean(clash));
  note.hidden = !clash && fractional.length === 0;
  if (note.hidden) return;
  if (clash) {
    const [label, group] = clash;
    const all = group.length === 2 ? `${group[0]} and ${group[1]} both ship`
                                   : `${group.join(", ")} all ship`;
    note.textContent = `${all} as ${family}_${label}, so they cannot both be `
      + `built. Saving will refuse this.`;
    return;
  }
  const said = fractional.map(
    (size, at) => `${size}${at === 0 ? " ships" : ""} as `
                  + `${family}_${sizeLabel(size)}`);
  note.textContent = `${said.join(", ")}, which is what the device lists `
    + `${fractional.length === 1 ? "it" : "them"} as.`;
}

export function showShipsAs() {
  spellShipsAs(shipsAs, joinSizeBoxes(SIZE_FIELDS, exportForm.elements.size_more),
               familyLabel());
  spellShipsAs(modShipsAs,
               joinSizeBoxes(MOD_FIELDS, exportForm.elements.mod_more),
               familyLabel() + modSuffix());
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
      // Still sweeping, and counting only from the first size that lands.
      // Sizes run across a pool, so nothing at all comes back until one of
      // them finishes: a determinate bar here would stop the sweep, sit at a
      // frozen "0 of 16" for as long as the first size takes, and then start
      // filling -- which is two starts, and the first of them looks stalled.
      // The total goes in the label so the scale is still said out loud.
      //
      // Restarting the clock here is what it is for: the estimate wants the
      // build, not the save and the planning in front of it.
      progress.start(`building ${step.total} `
                     + `size${step.total === 1 ? "" : "s"}…`);
    } else {
      builtNote.textContent = "everything is already current";
      progress.end();
    }
  } else if (step.event === "size") {
    progress.show(step.done, step.total, `${step.family} ${step.size}`);
  } else if (step.event === "failed") {
    // One size of many, and the build carries on: the bar keeps running and
    // the note says which one went wrong.
    builtNote.textContent = `${step.family} ${step.size}: ${step.error}`;
  } else if (step.event === "error") {
    progress.end();
    builtNote.textContent = step.error;
  } else if (step.event === "done") {
    progress.end();
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
    // Where they went is not in it: the note has one reserved line in the
    // foot, an output path is most of a panel wide, and the box three rows up
    // is already showing the folder this went to.
    //
    // A count only while there is one to give. A run that built every size has
    // nothing already current, and "0 already current" beside its own answer
    // reads as a second and worse one -- the same rule a failure and a removal
    // keep, each named only where there is one.
    const parts = [
      made && `${made} built${size}`,
      kept && `${kept} already current${had}`,
      failed && `${failed} failed`,
      gone && `removed ${step.removed.join(", ")}`,
    ].filter(Boolean);
    // A run with no size in it at all leaves every count out, and the foot
    // keeps a line for this note either way: an empty one reads as a build
    // that never answered rather than one with nothing to do.
    builtNote.textContent = parts.join(", ") || "nothing to build";
  }
}

// Both buttons are out while one of them is working. A build is minutes with
// the fallbacks on, the server runs one at a time, and a second press would
// only queue a run behind the one whose progress is on screen.
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
    progress.start(`${force ? "rebuilding" : "planning"} ${label}…`);
    builtNote.textContent = "";
    if (!saveButton.hidden && knobsDiffer() && !(await saveKnobs())) {
      // With the reason, which is the half worth having: a refusal here is
      // something to act on -- a name another family has taken, a size the
      // device could not read -- and saveKnobs writes it under Save, which is
      // a bar this tab does not show. Said here it is beside the press that
      // failed. The foot grows for it, as it does for any other error.
      builtNote.textContent = `not built: ${label} could not be saved`
        + (savedNote.textContent ? `\n${savedNote.textContent}` : "");
      return;
    }
    await streamInto("/build", {family: family, force: force},
                     showStep, builtNote);
  } finally {
    // Whatever happened -- a dropped connection, a line that would not parse --
    // the buttons come back, or the panel is dead until a reload. The bar
    // goes with them: a dropped connection would otherwise leave it sitting at
    // whatever fraction it had reached, saying a run is still going.
    progress.end();
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
  // Both notes, whatever changed: the name is in the text they carry, and the
  // suffix is in the second one's.
  showShipsAs();
  showSaveState();
  // Everything here reaches the page and not only the build. The fallbacks
  // decide which face fills for the family; the coverage decides what the page
  // is allowed to draw at all, so a tick redraws whether the bundled set is on
  // or not. It used to redraw only while that set was on, back when coverage
  // did nothing but choose which bundled faces to load -- which left ticking
  // the range a blank page had just asked for doing nothing at all.
  if (FALLBACK_FIELDS.has(field.name) || field.dataset.preset ||
      field.name === "ranges") {
    scheduleRender();
  }
}

exportForm.addEventListener("input", (event) => exportEdited(event.target));

//: A size box, left. Snapping on the way out rather than on every keystroke:
//: correcting 13.3 to 13.25 while somebody is still typing 13.375 would fight
//: the keyboard. This is the same moment the knobs snap in, which is what
//: makes the two halves of the page agree about what a size can be.
export function sizeLeft(field) {
  const name = field && field.name;
  const one = SIZE_FIELDS.includes(name) || MOD_FIELDS.includes(name);
  const list = name === "size_more" || name === "mod_more";
  if (!one && !list) return;
  const next = one ? snapSize(field.value) : snapSizeList(field.value);
  if (next === field.value) return;
  field.value = next;
  // By the same road a keystroke takes: a value the panel corrected is still a
  // value the config has not got, and the note under the boxes is about what
  // is in them now rather than what was typed into them.
  exportEdited(field);
}

exportForm.addEventListener("change", (event) => sizeLeft(event.target));

// --- looking at a size ----------------------------------------------------
// The boxes say what will ship and the knob on the left says what you are
// looking at, and the two are easy to set apart and tedious to keep together:
// judging four shipped sizes meant typing each of them into the knob by hand.
// A box's title moves the knob to what that box holds, which is the whole
// distance between a size being in the list and having been looked at.
//
// The knob is a view setting, so this writes nothing into the config and
// leaves the Save button where it was.
function previewSize(name) {
  const size = Number(snapSize(exportForm.elements[name].value));
  // An empty box, or one still being typed into, has no size to show yet.
  if (!(size > 0)) return;
  setField(form.elements.size, size);
}

//: Wired by the entry point rather than on import: the press reaches across to
//: the knob form, and a module body runs while its imports may still be on
//: their way up.
export function wireSizeTitles() {
  for (const title of exportForm.querySelectorAll("[data-preview-size]")) {
    title.addEventListener(
      "click", () => previewSize(title.dataset.previewSize));
  }
}

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
    progress.show(step.got, step.bytes, step.name, spellBytes);
  }
}

export async function fetchFallbacks() {
  // Out for the duration. It is a 20 MB download with a CJK face in it, and a
  // button that still looks pressable is one people press again.
  fetchButton.disabled = true;
  fetchNote.textContent = "";
  progress.start("asking for the fallback faces…");
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
    progress.end();
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
