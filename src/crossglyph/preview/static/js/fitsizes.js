// --- Fit to grid ----------------------------------------------------------
// Suggests render sizes whose straight strokes land more cleanly on the
// device's pixels, for the sizes in the boxes or for a range of whole sizes.
// Every candidate keeps its label, so the numbers in the reader's Font Size
// list stay the same. The section only suggests: each value is a press away
// from being looked at, and Apply puts the ticked ones in the boxes as an
// unsaved edit, which Save and Build then treat like typing.

import {form} from "./dom.js";
import {exportEdited, exportForm, readSteps, showSize, snapSize} from "./export.js";
import {familyPicker} from "./family.js";
import {openFold} from "./fold.js";
import {body} from "./render.js";

const toggle = document.getElementById("fit-toggle");
const panel = document.getElementById("fit-panel");
const mode = document.getElementById("fit-mode");
const rangeFields = document.getElementById("fit-range");
const low = document.getElementById("fit-low");
const high = document.getElementById("fit-high");
const count = document.getElementById("fit-count");
const runButton = document.getElementById("fit-run");
const sample = document.getElementById("fit-sample");
const table = document.getElementById("fit-table");
const note = document.getElementById("fit-note");
const builds = document.getElementById("fit-builds");
const applyButton = document.getElementById("fit-apply");
const undoButton = document.getElementById("fit-undo");

const FIRST_ROW = ["size1", "size2", "size3", "size4"];
const SECOND_ROW = ["mod1", "mod2", "mod3", "mod4"];
//: The fields past the four boxes in each row, which take a list.
const SPILL = {first: "size_more", second: "mod_more"};
const TITLES = ["Small", "Medium", "Large", "Extra Large"];
//: A suggestion is ticked for you when it gains at least this much.
const WORTH = 3;
//: The size knob's range, which a range of sizes has to stay inside.
const SIZE_MIN = 6, SIZE_MAX = 40;

//: One per suggestion: the box it would fill, what the box held when it was
//: scored, and the two values offered.
let rows = [];
//: What Apply wrote, box by box, and what each box held before it.
let applied = null;
//: The family the suggestions were found for.
let foundFor = null;
let controller = null;
let runs = 0;

function titleOf(box) {
  const first = FIRST_ROW.indexOf(box);
  return first >= 0 ? TITLES[first]
    : `${TITLES[SECOND_ROW.indexOf(box)]}, more sizes`;
}

function filled(box) {
  return Number(snapSize(exportForm.elements[box].value)) > 0;
}

function spilled(name) {
  return String(exportForm.elements[name]?.value ?? "")
    .split(/[\s,]+/).filter(Boolean).length;
}

function round(fit) {
  return fit === null || fit === undefined ? "-" : String(Math.round(fit));
}

// What Apply would leave the family as, said before it is pressed. An empty
// suffix makes the second row more sizes of the same family.
function showBuilds() {
  const name = exportForm.elements.name.value || familyPicker.value || "This family";
  const suffix = exportForm.elements.mod_suffix.value.trim();
  const boxes = new Set(rows.map(row => row.box));
  const first = FIRST_ROW.filter(b => boxes.has(b) || filled(b)).length
    + spilled(SPILL.first);
  const second = SECOND_ROW.filter(b => boxes.has(b) || filled(b)).length
    + spilled(SPILL.second);
  builds.textContent = !second ? `Builds ${name} with ${first} sizes.`
    : !suffix ? `Builds one family of ${first + second} sizes. `
      + "Fill in the suffix under More sizes to make them two families."
    : `Builds ${name} (${first} sizes) and ${name}${suffix} (${second} sizes).`;
}

//: Marks whichever offered value the page is showing. The page can move off
//: it by other means, so render.js calls this after every page as well.
export function syncFitMarks() {
  const showing = Number(form.elements.size.value);
  for (const row of rows) {
    for (const button of [row.now, row.pick]) {
      button.classList.toggle("showing", Number(button.dataset.size) === showing);
    }
  }
}

function valueButton(size) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "fit-value mono";
  button.dataset.size = String(size);
  button.textContent = String(size);
  button.title = "Show the page at this size";
  button.addEventListener("click", () => {
    showSize(String(size));
    syncFitMarks();
  });
  return button;
}

function addRow(box, now, pick, fits, ranged) {
  const row = document.createElement("div");
  row.className = "fit-row";
  const name = document.createElement("span");
  name.className = "fit-name";
  name.textContent = titleOf(box);
  const nowButton = valueButton(now);
  const pickButton = valueButton(pick ?? now);
  const score = document.createElement("span");
  score.className = "fit-score mono";
  const nowFit = fits.get(now), pickFit = fits.get(pick ?? now);
  score.textContent = pick === null || pick === now ? round(nowFit)
    : `${round(nowFit)} → ${round(pickFit)}`;
  const tick = document.createElement("input");
  tick.type = "checkbox";
  tick.setAttribute("aria-label", `Use ${pick} for ${titleOf(box)}`);
  // Something to change is a suggestion the box does not already hold. A
  // range starts from labels the boxes may not hold at all, so all of it is
  // the user's to take; for their own sizes only a real gain is ticked.
  const held = exportForm.elements[box].value;
  const changes = pick !== null && String(pick) !== snapSize(held);
  tick.hidden = !changes;
  tick.checked = changes && (ranged || pickFit - nowFit >= WORTH);
  row.append(name, nowButton, pickButton, score, tick);
  table.append(row);
  rows.push({box, held, now: nowButton, pick: pickButton, value: pick, tick});
}

// The server's refusal as a sentence. A malformed request comes back as a
// list of parts, each with its own message.
function failure(text) {
  let detail;
  try {
    detail = JSON.parse(text).detail;
  } catch {
    return text;
  }
  if (Array.isArray(detail)) return detail.map(part => part.msg).join(". ");
  return detail ?? text;
}

// A range is whole sizes inside the size knob's range, smaller first.
function rangeProblem() {
  const from = Number(low.value), to = Number(high.value);
  if (![from, to].every(Number.isInteger) || !low.value.trim() || !high.value.trim()) {
    return "A range is two whole sizes, such as 12 and 19.";
  }
  if (from < SIZE_MIN || to > SIZE_MAX || from >= to) {
    return `A range runs from a smaller size to a larger one, between ${SIZE_MIN} and ${SIZE_MAX}.`;
  }
  return null;
}

function clearFit() {
  rows = [];
  table.replaceChildren();
  note.textContent = "";
  builds.textContent = "";
  sample.textContent = "";
  applyButton.disabled = true;
  undoButton.hidden = true;
  applied = null;
}

async function runFit() {
  const ranged = mode.value === "range";
  const boxes = ranged
    ? [...FIRST_ROW, ...SECOND_ROW].slice(0, Number(count.value))
    : [...FIRST_ROW, ...SECOND_ROW].filter(filled);
  stopFit();
  clearFit();
  if (ranged && rangeProblem()) {
    note.textContent = rangeProblem();
    return;
  }
  if (!boxes.length) {
    note.textContent = "There are no sizes in the boxes yet. Choose a range instead.";
    return;
  }
  const request = {...body(), ...(ranged
    ? {low: Number(low.value), high: Number(high.value), count: Number(count.value)}
    : {sizes: boxes.map(box => Number(snapSize(exportForm.elements[box].value)))})};
  const mine = ++runs;
  controller = new AbortController();
  foundFor = familyPicker.value;
  // A count in the note rather than a bar: the export panel's one bar is the
  // build's, in its foot, where a change of height cannot move the boxes.
  note.textContent = "Scoring sizes";
  runButton.disabled = true;
  const fits = new Map();
  let index = 0, total = 0;
  try {
    const response = await fetch("/fit-sizes", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify(request), signal: controller.signal});
    if (mine !== runs) return;
    if (!response.ok) {
      note.textContent = failure(await response.text());
      return;
    }
    await readSteps(response, (step) => {
      if (mine !== runs) return;
      if (step.event === "plan") {
        total = step.total;
        sample.textContent = `Scored on the ${step.letters} letters on the page.`;
      } else if (step.event === "candidate") {
        fits.set(step.size, step.fit);
        note.textContent = `Scoring ${step.done} of ${total}`;
      } else if (step.event === "label") {
        addRow(boxes[index++], step.now, step.pick, fits, ranged);
      } else if (step.event === "error") {
        note.textContent = step.error;
      }
    });
    if (mine !== runs) return;
    if (note.textContent.startsWith("Scoring")) note.textContent = "";
    applyButton.disabled = !rows.some(row => !row.tick.hidden);
    showBuilds();
    syncFitMarks();
  } catch (error) {
    if (error.name !== "AbortError" && mine === runs) note.textContent = String(error);
  } finally {
    if (mine === runs) {
      runButton.disabled = false;
      controller = null;
    }
  }
}

function applyFit() {
  if (familyPicker.value !== foundFor) {
    clearFit();
    note.textContent = "The family has changed. Press Find sizes again.";
    return;
  }
  applied = new Map();
  let skipped = 0;
  for (const row of rows) {
    if (row.tick.hidden || !row.tick.checked) continue;
    const field = exportForm.elements[row.box];
    // A box edited since it was scored is the user's newer word.
    if (field.value !== row.held) {
      skipped++;
      continue;
    }
    applied.set(row.box, {was: field.value, wrote: String(row.value)});
    field.value = String(row.value);
    exportEdited(field);
  }
  if ([...applied.keys()].some(box => SECOND_ROW.includes(box))) openFold("mod");
  applyButton.disabled = true;
  undoButton.hidden = !applied.size;
  const changed = applied.size;
  note.textContent = (changed ? `${changed} size${changed === 1 ? "" : "s"} changed. `
    + "Save or Build to keep them." : "Nothing was changed.")
    + (skipped ? ` ${skipped} box${skipped === 1 ? " was" : "es were"} changed since `
      + "the search and left as typed." : "");
}

function undoFit() {
  for (const [box, {was, wrote}] of applied) {
    const field = exportForm.elements[box];
    // Only what Apply wrote: a box edited afterwards keeps the edit.
    if (field.value !== wrote) continue;
    field.value = was;
    exportEdited(field);
  }
  applied = null;
  undoButton.hidden = true;
  note.textContent = "The sizes are back as they were.";
}

function stopFit() {
  runs++;
  controller?.abort();
  controller = null;
  runButton.disabled = false;
}

//: A new family has sizes of its own, so suggestions found for the last one
//: go. Called after the change has gone through: a refused change leaves the
//: family, and its suggestions, where they were.
export function familyMoved() {
  if (familyPicker.value === foundFor) return;
  stopFit();
  clearFit();
  foundFor = null;
}

// The range starts from the sizes the family has, so switching to it is a
// small step from what is there rather than a blank form.
function prefillRange() {
  const labels = [...FIRST_ROW, ...SECOND_ROW].filter(filled)
    .map(box => Math.floor(Number(snapSize(exportForm.elements[box].value)) + 0.5));
  low.value = String(labels.length ? Math.min(...labels) : 12);
  high.value = String(labels.length ? Math.max(...labels) : 19);
  count.value = labels.length > 4 ? "8" : "4";
}

mode.addEventListener("change", () => {
  rangeFields.hidden = mode.value !== "range";
  if (mode.value === "range") prefillRange();
});
toggle.addEventListener("click", () => {
  if (!low.value) prefillRange();
});
runButton.addEventListener("click", runFit);
applyButton.addEventListener("click", applyFit);
undoButton.addEventListener("click", undoFit);
// The section sits inside the export form, whose listeners would take its
// fields for settings and offer to save them.
for (const kind of ["input", "change"]) {
  panel.addEventListener(kind, (event) => event.stopPropagation());
}
