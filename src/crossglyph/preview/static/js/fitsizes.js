// --- Fit to grid ----------------------------------------------------------
// Suggests render sizes whose straight strokes land more cleanly on the
// device's pixels, for the sizes in the boxes or for a range of whole sizes.
// Every candidate keeps its label, so the numbers in the reader's Font Size
// list stay the same. The section only suggests: each value is a press away
// from being looked at, and Apply puts the ticked ones in the boxes as an
// unsaved edit, which Save and Build then treat like typing.

import {form} from "./dom.js";
import {SIZE_MAX, SIZE_MIN, buildsPhrase, exportEdited, exportForm, readSteps,
        rowCounts, showSize, snapSize} from "./export.js";
import {familyPicker} from "./family.js";
import {openFold} from "./fold.js";
import {body} from "./render.js";

const toggle = document.getElementById("fit-toggle");
const panel = document.getElementById("fit-panel");
const toMine = document.getElementById("fit-mode-mine");
const toRange = document.getElementById("fit-mode-range");
const mineSays = document.getElementById("fit-mine-says");
const rangeFields = document.getElementById("fit-range");
const low = document.getElementById("fit-low");
const stepField = document.getElementById("fit-step");
const count = document.getElementById("fit-count");
const targets = document.getElementById("fit-targets");
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
//: A suggestion is ticked for you when it gains at least this much.
const WORTH = 3;
//: What My sizes says when the boxes hold none.
const NO_SIZES = "There are no sizes in the boxes yet. Choose Range instead.";

//: One per suggestion: the box it would fill, what the box held when it was
//: scored, and the two values offered.
let rows = [];
//: What Apply wrote, box by box, and what each box held before it.
let applied = null;
//: The family the suggestions were found for.
let foundFor = null;
let controller = null;
let runs = 0;

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

// What Apply would leave the family as, said only when that is not what the
// boxes build now. The line under the boxes says what they build already.
function showBuilds() {
  const listed = new Map(rows.map(row => [row.box, row]));
  // A box with a row ends up holding a size unless the row removes it.
  const kept = (box) => (listed.has(box) ? !listed.get(box).removed : filled(box));
  const first = FIRST_ROW.filter(kept).length + spilled(SPILL.first);
  const second = SECOND_ROW.filter(kept).length + spilled(SPILL.second);
  const [nowFirst, nowSecond] = rowCounts();
  builds.textContent = first === nowFirst && second === nowSecond ? ""
    : `After Apply, it builds ${buildsPhrase(first, second)}.`;
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

//: What a cell shows until its result arrives.
const WAITING = "…";

// A size the page can be shown at, once there is one. Until its row is
// filled it holds the place, so the row is its final width from the start.
function valueButton(size) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "fit-value mono";
  button.title = "Show the page at this size";
  setValue(button, size);
  button.addEventListener("click", () => {
    if (!button.dataset.size) return;
    showSize(button.dataset.size);
    syncFitMarks();
  });
  return button;
}

function setValue(button, size) {
  const known = size !== null && size !== undefined;
  button.dataset.size = known ? String(size) : "";
  button.textContent = known ? String(size) : WAITING;
  button.disabled = !known;
}

// Every row at once, before any result: the section takes its full height
// when the search starts rather than growing as sizes arrive. A range's
// sizes are the server's to choose, so they wait too.
function addRow(box, now) {
  const row = document.createElement("div");
  row.className = "fit-row";
  const score = document.createElement("span");
  score.className = "fit-score mono";
  score.textContent = WAITING;
  const tick = document.createElement("input");
  tick.type = "checkbox";
  tick.hidden = true;
  const entry = {box, held: exportForm.elements[box].value, now: valueButton(now),
                 pick: valueButton(null), score, value: null, tick};
  row.append(entry.now, entry.pick, score, tick);
  table.append(row);
  rows.push(entry);
}

// A box past a range's count. A range is the family's new size list, so
// Apply empties it; the row says so before anything is written.
function addRemovedRow(box) {
  addRow(box, Number(snapSize(exportForm.elements[box].value)));
  const entry = rows.at(-1);
  entry.removed = true;
  entry.value = "";
  entry.pick.textContent = "removed";
  entry.score.textContent = "";
  entry.tick.hidden = false;
  entry.tick.checked = true;
  entry.tick.setAttribute("aria-label", `Remove size ${entry.now.dataset.size}`);
}

function fillRow(entry, now, pick, fits, ranged) {
  entry.filled = true;
  setValue(entry.now, now);
  setValue(entry.pick, pick ?? now);
  entry.value = pick;
  const nowFit = fits.get(now), pickFit = fits.get(pick ?? now);
  // The score the suggestion would have, and what it gains, the way the
  // Grid Fit under the page says it. The score now is a hover away.
  const gain = Number(round(pickFit)) - Number(round(nowFit));
  entry.score.textContent = pick === null || pick === now || !(gain > 0)
    ? round(pickFit) : `${round(pickFit)} (+${gain})`;
  if (pick !== null && pick !== now) {
    entry.score.title = `${round(nowFit)} now, ${round(pickFit)} suggested`;
  }
  entry.tick.setAttribute("aria-label", `Use ${pick} instead of ${now}`);
  // Something to change is a suggestion the box does not already hold. A
  // range starts from labels the boxes may not hold at all, so all of it is
  // the user's to take; for their own sizes only a real gain is ticked.
  const changes = pick !== null && String(pick) !== snapSize(entry.held);
  entry.tick.hidden = !changes;
  entry.tick.checked = changes && (ranged || pickFit - nowFit >= WORTH);
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

// The sizes a range will try: `count` whole sizes counting up from its start
// by its step. What is wrong with it instead, when something is, in words.
function rangeSizes() {
  const start = Number(low.value);
  if (!low.value.trim() || !Number.isInteger(start) || start < SIZE_MIN || start > SIZE_MAX) {
    return {problem: `Start at a whole size between ${SIZE_MIN} and ${SIZE_MAX}.`};
  }
  const step = Number(stepField.value), many = Number(count.value);
  const end = start + step * (many - 1);
  if (end > SIZE_MAX) {
    return {problem: `That runs to ${end}, past the largest size, ${SIZE_MAX}.`};
  }
  return {sizes: Array.from({length: many}, (_, i) => start + i * step)};
}

// What Find sizes will try, listed in both modes on the same line: a range's
// sizes as its fields change, or the sizes in the boxes as they are edited.
export function showFitTargets() {
  stepField.disabled = count.value === "1";
  if (toRange.getAttribute("aria-pressed") !== "true") {
    const mine = [...FIRST_ROW, ...SECOND_ROW].filter(filled)
      .map(box => snapSize(exportForm.elements[box].value));
    targets.textContent = mine.length ? `Tries ${mine.join(", ")}` : NO_SIZES;
    return;
  }
  const {sizes, problem} = rangeSizes();
  targets.textContent = problem ?? `Tries ${sizes.join(", ")}`;
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
  const ranged = toRange.getAttribute("aria-pressed") === "true";
  const boxes = ranged
    ? [...FIRST_ROW, ...SECOND_ROW].slice(0, Number(count.value))
    : [...FIRST_ROW, ...SECOND_ROW].filter(filled);
  stopFit();
  clearFit();
  if (ranged && rangeSizes().problem) {
    note.textContent = rangeSizes().problem;
    return;
  }
  if (!boxes.length) {
    note.textContent = NO_SIZES;
    return;
  }
  const request = {...body(), ...(ranged
    ? {low: Number(low.value), step: Number(stepField.value), count: Number(count.value)}
    : {sizes: boxes.map(box => Number(snapSize(exportForm.elements[box].value)))})};
  const mine = ++runs;
  controller = new AbortController();
  foundFor = familyPicker.value;
  for (const box of boxes) {
    addRow(box, ranged ? null : Number(snapSize(exportForm.elements[box].value)));
  }
  if (ranged) {
    for (const box of [...FIRST_ROW, ...SECOND_ROW].slice(boxes.length).filter(filled)) {
      addRemovedRow(box);
    }
  }
  showBuilds();
  // A count in the status line rather than a bar: the export panel's one bar
  // is the build's, in its foot. The same line then says what the scores
  // rest on, so nothing appears or goes as the run ends.
  sample.textContent = "Scoring sizes";
  runButton.disabled = true;
  const fits = new Map();
  let index = 0, total = 0, letters = 0;
  try {
    const response = await fetch("/fit-sizes", {
      method: "POST", headers: {"content-type": "application/json"},
      body: JSON.stringify(request), signal: controller.signal});
    if (mine !== runs) return;
    if (!response.ok) {
      clearFit();
      note.textContent = failure(await response.text());
      return;
    }
    await readSteps(response, (step) => {
      if (mine !== runs) return;
      if (step.event === "plan") {
        total = step.total;
        letters = step.letters;
      } else if (step.event === "candidate") {
        fits.set(step.size, step.fit);
        sample.textContent = `Scoring ${step.done} of ${total}`;
      } else if (step.event === "label") {
        fillRow(rows[index++], step.now, step.pick, fits, ranged);
      } else if (step.event === "error") {
        note.textContent = step.error;
      }
    });
    if (mine !== runs) return;
    sample.textContent = `Scored on the ${letters} letters on the page.`;
  } catch (error) {
    if (error.name !== "AbortError" && mine === runs) note.textContent = String(error);
  } finally {
    if (mine === runs) {
      // A run that ended early leaves rows it never reached. They go, rather
      // than sit there waiting for an answer that is not coming, and so do
      // the removals, which only stand with the whole range beside them.
      const complete = index === boxes.length;
      rows = rows.filter(row => (row.removed ? complete : row.filled));
      table.replaceChildren(...rows.map(entry => entry.now.parentElement));
      applyButton.disabled = !rows.some(row => !row.tick.hidden);
      if (rows.length) showBuilds(); else builds.textContent = "";
      syncFitMarks();
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
  showBuilds();
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
  showBuilds();
}

function stopFit() {
  runs++;
  controller?.abort();
  controller = null;
  runButton.disabled = false;
}

//: A new family has sizes of its own, so suggestions found for the last one
//: go. Called after the change has gone through, since a refused change
//: leaves the family and its suggestions where they were, and after every
//: page, since a family can also change when the folder is read again.
export function familyMoved() {
  if (foundFor === null || familyPicker.value === foundFor) return;
  stopFit();
  clearFit();
  foundFor = null;
}

// The range starts from the sizes the family has, so switching to it is a
// small step from what is there rather than a blank form.
function prefillRange() {
  const labels = [...new Set([...FIRST_ROW, ...SECOND_ROW].filter(filled)
    .map(box => Math.floor(Number(snapSize(exportForm.elements[box].value)) + 0.5)))]
    .sort((a, b) => a - b);
  // The step the sizes have most often, the smaller one on a tie, within the
  // steps the menu offers.
  const gaps = new Map();
  labels.slice(1).forEach((label, i) => {
    const gap = Math.min(3, label - labels[i]);
    gaps.set(gap, (gaps.get(gap) || 0) + 1);
  });
  const usual = [...gaps].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0] ?? 1;
  low.value = String(labels[0] ?? 12);
  stepField.value = String(usual);
  count.value = String(Math.min(8, labels.length) || 4);
  showFitTargets();
}

// Two halves of one toggle. Range swaps its fields in where My sizes says
// what it does, so the row keeps its height and Find sizes stays put.
function setMode(ranged) {
  toMine.setAttribute("aria-pressed", String(!ranged));
  toRange.setAttribute("aria-pressed", String(ranged));
  mineSays.hidden = ranged;
  rangeFields.hidden = !ranged;
  if (ranged) prefillRange();
  showFitTargets();
}

toMine.setAttribute("aria-pressed", "true");
toRange.setAttribute("aria-pressed", "false");
toMine.addEventListener("click", () => setMode(false));
toRange.addEventListener("click", () => setMode(true));
low.addEventListener("input", showFitTargets);
stepField.addEventListener("change", showFitTargets);
count.addEventListener("change", showFitTargets);
toggle.addEventListener("click", () => {
  if (!low.value) prefillRange();
  showFitTargets();
});
runButton.addEventListener("click", runFit);
applyButton.addEventListener("click", applyFit);
undoButton.addEventListener("click", undoFit);
// The section sits inside the export form, whose listeners would take its
// fields for settings and offer to save them.
for (const kind of ["input", "change"]) {
  panel.addEventListener(kind, (event) => event.stopPropagation());
}
