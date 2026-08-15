// What this install is, and whether there is a newer one: the island under
// the specimen. One row -- the version on the left, the update on the right --
// over the sentence that says which render core it carries.
import {streamInto} from "./export.js";
import {progressBar, spellBytes} from "./progress.js";

const island = document.getElementById("about");
const number = document.getElementById("about-number");
const home = document.getElementById("about-home");
const state = document.getElementById("about-state");
const detail = document.getElementById("about-detail");
const button = document.getElementById("check-now");
const updateButton = document.getElementById("update-now");
const updateNote = document.getElementById("updated");
const progress = progressBar(document.getElementById("update-progress"));

// The same count the CLI uses, in render/stamp.py: the page and `crossglyph
// --version` report one fact, and two spellings of it is one more thing to
// reconcile when somebody quotes it in a report.
const SHORT = 12;

const MINUTE = 60, HOUR = 3600, DAY = 86400;

const UNREACHABLE = "Could not reach the update server.";

// Said in the coarsest unit that is still true. "3 hours ago" is what anybody
// wants from this line; a timestamp is not.
function ago(seconds) {
  if (seconds < MINUTE) return "just now";
  if (seconds < HOUR) return `${Math.floor(seconds / MINUTE)} minutes ago`;
  if (seconds < DAY) return `${Math.floor(seconds / HOUR)} hours ago`;
  return `${Math.floor(seconds / DAY)} days ago`;
}

// The answer, not the asking. Somebody reading this line, or pressing the
// button above it, wants to know whether there is an update; when the looking
// last happened is a detail about that answer and goes on the line below.
function checkedLine(about) {
  if (about.checking_off) return "Update checks are off.";
  if (about.error) return UNREACHABLE;
  if (!about.checked_at) return "Not checked yet.";
  return "Up to date.";
}

// Which is worth keeping, since an answer from a week ago is worth less than
// one from a minute ago, and only this says which it is.
function askedLine(about) {
  if (about.checking_off || about.error || !about.checked_at) return "";
  return `Checked ${ago(Date.now() / 1000 - about.checked_at)}.`;
}

// What a restart would run, when that is not what is running. The server
// reads it off the disk, so a reload and a second browser are told as much as
// the page that pressed the button; this holds it for the one moment the
// server has not been asked again, which is the end of an update.
let installed = null;

// Which leaves nothing to press. What is installed does not become what is
// running until the tool is started again, and asking again can only find the
// same release a second time.
function showInstalled() {
  state.textContent = `${installed} installed.`;
  updateButton.hidden = true;
  button.hidden = true;
}

export function showAbout(about) {
  number.textContent = about.version;
  if (about.home) home.href = about.home;
  installed = installed || about.pending || null;
  if (installed) {
    showInstalled();
  } else {
    // One thing on the right, which is what keeps the row to one line. A
    // release to install is the only answer worth having while there is one,
    // so it replaces the line about when the asking last happened.
    state.textContent = about.available
      ? `${about.available} is available.` : checkedLine(about);
    // And one button under it, for the one thing worth pressing: asking again
    // says nothing new once the answer is on screen.
    updateButton.hidden = !(about.can_self_update && about.available);
    button.hidden = !updateButton.hidden;
  }

  const said = [];
  const asked = askedLine(about);
  if (asked) said.push(asked);
  if (about.firmware) {
    said.push("Render core built from crosspoint-reader " +
              `${about.firmware.slice(0, SHORT)}.`);
  }
  // Why a release is on offer that the page load did not mention: the button
  // asked, and asking is answered even about the one a rollback turned down.
  if (about.turned_down && about.available) {
    said.push(`You rolled back from ${about.available}, ` +
              "so checks stay quiet about it.");
  }
  // Decided by the server, which is where the same rule serves the command
  // line. Empty for a release with nothing to update to, which is the case
  // that should say nothing at all.
  if (about.notice) said.push(about.notice);
  detail.textContent = said.join(" ");

  island.title = [`CrossGlyph ${about.version}`, ...said].join("\n");
}

// What the install left in the workspace, said the way the command line says
// it: one install, one sentence, whichever surface asked for it.
function keptLine(kept) {
  return kept.map(name =>
    ` Kept your fonts/${name}. The new one is beside it as ` +
    `${name.split("/").pop()}.new.`).join("");
}

export function showUpdateStep(step) {
  if (step.event === "plan") {
    updateNote.textContent = step.converting
      ? `Converting this install to ${step.version}.`
      : `Installing ${step.version}.`;
  } else if (step.event === "step") {
    progress.show(step.got, step.bytes, "downloading", spellBytes);
  } else if (step.event === "current") {
    updateNote.textContent = `CrossGlyph ${step.version} is up to date.`;
  } else if (step.event === "error") {
    updateNote.textContent = step.error;
  } else if (step.event === "done") {
    installed = step.version;
    showInstalled();
    updateNote.textContent =
      `${step.version} installed. Restart CrossGlyph to use it.` +
      keptLine(step.kept) +
      (step.staged.length
        ? ` ${step.staged.join(" and ")} will be replaced at the next launch.`
        : "") +
      (step.converting
        ? " The files at the root are no longer read." : "");
  }
}

// Its own button, so this is a handle the module owns rather than a name
// reaching across modules.
updateButton.addEventListener("click", async () => {
  // Out for the duration. It is a download and an extract, and a button that
  // still looks pressable is one people press again, mid-swap.
  updateButton.disabled = true;
  updateNote.textContent = "";
  progress.start("asking for the new release…");
  try {
    await streamInto("/update", {}, showUpdateStep, updateNote);
  } finally {
    // Whatever ended it, including a dropped connection: a bar left sitting
    // at some fraction says the update is still running.
    progress.end();
    updateButton.disabled = false;
  }
});

button.addEventListener("click", () => {
  button.disabled = true;
  state.textContent = "Checking...";
  fetch("/update/check", {method: "POST"})
    .then(r => r.json())
    .then(showAbout)
    // A manual check that says nothing when the answer never comes reads as
    // broken, which is the one thing it must not do.
    .catch(() => { state.textContent = UNREACHABLE; })
    .finally(() => { button.disabled = false; });
});
