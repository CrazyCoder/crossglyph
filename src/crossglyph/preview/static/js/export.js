import {familyEntries, familyPicker} from "./family.js";
import {body, scheduleRender} from "./render.js";
import {endProgress, showProgress, startProgress} from "./progress.js";
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

export function fillPresets(presets) {
  presetNames = presets.map(preset => preset.name);
  presetList.replaceChildren(...presets.map(preset => {
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
  modName.textContent = sizes
    ? (familyPicker.value || "this family") + (suffix.value || "Mod")
    : "a second family";
}

// The config spells coverage as one comma-separated string, because that is
// what the converter takes; the panel spells it as ticks.
export function showExport(entry) {
  const settings = (entry && entry.export) || null;
  exportForm.hidden = !settings;
  if (!settings) return;
  showSizes(settings);
  exportForm.elements.ranges.value = settings.ranges;
  exportForm.elements.fallbacks.checked = settings.fallbacks;
  const ticked = new Set(settings.intervals.split(",").map(t => t.trim()));
  for (const box of presetBoxes()) box.checked = ticked.has(box.value);
  for (const field of ["fallback1", "fallback2"]) {
    exportForm.elements[field].value = settings[field] || "";
  }
}

export function exportSettings() {
  return {
    sizes: joinSizeBoxes(SIZE_FIELDS, exportForm.elements.size_more),
    sizes_mod: joinSizeBoxes(MOD_FIELDS, exportForm.elements.mod_more),
    mod_suffix: exportForm.elements.mod_suffix.value.trim(),
    intervals: presetBoxes().filter(box => box.checked)
                            .map(box => box.value).join(","),
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
    builtNote.textContent =
      `${count("built")} built, ${count("skipped")} already current`
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
    let response;
    try {
      response = await fetch("/build", {
        method: "POST", headers: {"content-type": "application/json"},
        body: JSON.stringify({family: family, force: force})});
    } catch (error) {
      builtNote.textContent = String(error);
      return;
    }
    if (!response.ok) { builtNote.textContent = await response.text(); return; }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      pending += decoder.decode(value, {stream: true});
      const lines = pending.split("\n");
      // The last piece is whatever arrived without its newline yet.
      pending = lines.pop();
      for (const line of lines) if (line.trim()) showStep(JSON.parse(line));
    }
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

// Editing any of it offers a save, the same as a knob does. The output folder
// is the exception: it is all.conf's and saves itself below.
export const FALLBACK_FIELDS = new Set(["fallbacks", "fallback1", "fallback2"]);

exportForm.addEventListener("input", (event) => {
  if (event.target === outField) return;
  // Typing a second family's first size is what turns its suffix on.
  showModState();
  showSaveState();
  // The fallbacks reach the page as well as the build, so changing which face
  // fills for the family redraws it. A coverage tick only matters while the
  // bundled set is on, since that is the list it decides.
  if (FALLBACK_FIELDS.has(event.target.name) ||
      (event.target.dataset.preset && exportForm.elements.fallbacks.checked)) {
    scheduleRender();
  }
});

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
  haveFallbacks.textContent = where ? `— from ${tail}` : "— not fetched yet";
  haveFallbacks.title = where || "";
}

fetchButton.addEventListener("click", async () => {
  fetchNote.textContent = "fetching…";
  let response;
  try {
    response = await fetch("/fallbacks", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify({intervals: exportSettings().intervals})});
  } catch (error) {
    fetchNote.textContent = String(error);
    return;
  }
  if (!response.ok) { fetchNote.textContent = await response.text(); return; }
  const result = await response.json();
  fetchNote.textContent = `${result.faces} faces`;
  showFallbackState(result.where);
});

buildButtons[0].addEventListener(
  "click", (event) => buildFamilies(familyPicker.value, event.shiftKey));
buildButtons[1].addEventListener(
  "click", (event) => buildFamilies("", event.shiftKey));

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
