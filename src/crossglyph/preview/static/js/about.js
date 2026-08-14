// What this install is, in the two places that say so: the version in the top
// strip, and the sentence at the foot of the export panel. One shape fills
// both, from start.js at load and from the button after that.
import {streamInto} from "./export.js";
import {endProgress, showProgress, spellBytes,
        startProgress} from "./progress.js";

const strip = document.getElementById("version-strip");
const number = document.getElementById("version-number");
const dot = document.getElementById("version-dot");
const line = document.getElementById("about-line");
const detail = document.getElementById("about-detail");
const when = document.getElementById("checked-when");
const button = document.getElementById("check-now");
const updateRow = document.getElementById("update-row");
const updateButton = document.getElementById("update-now");
const updateNote = document.getElementById("updated");

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

function checkedLine(about) {
  if (about.checking_off) return "Update checks are off.";
  if (about.error) return UNREACHABLE;
  if (!about.checked_at) return "Not checked yet.";
  return `Checked ${ago(Date.now() / 1000 - about.checked_at)}.`;
}

export function showAbout(about) {
  number.textContent = about.version;
  dot.hidden = !about.available;
  line.textContent = about.available
    ? `CrossGlyph ${about.version}, ${about.available} is available`
    : `CrossGlyph ${about.version}`;

  const said = [];
  if (about.firmware) {
    said.push("Render core built from crosspoint-reader " +
              `${about.firmware.slice(0, SHORT)}.`);
  }
  // Decided by the server, which is where the same rule serves the command
  // line. Empty for a release with nothing to update to, which is the case
  // that should say nothing at all.
  if (about.notice) said.push(about.notice);
  detail.textContent = said.join(" ");
  when.textContent = checkedLine(about);
  // The button, only where pressing it would do something: an install that
  // owns its own files, with a release to install. Everywhere else the
  // sentence above says what to do instead.
  updateRow.hidden = !(about.can_self_update && about.available);

  strip.title = [`CrossGlyph ${about.version}`, ...said].join("\n");
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
    showProgress(step.got, step.bytes, "downloading", spellBytes);
  } else if (step.event === "current") {
    updateNote.textContent = `CrossGlyph ${step.version} is up to date.`;
  } else if (step.event === "error") {
    updateNote.textContent = step.error;
  } else if (step.event === "done") {
    // There is nothing more to press here: what is installed does not become
    // what is running until the tool is started again.
    updateRow.hidden = true;
    updateNote.textContent =
      `${step.version} installed. Restart CrossGlyph to use it.` +
      keptLine(step.kept) + (step.converting
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
  startProgress("asking for the new release…");
  try {
    await streamInto("/update", {}, showUpdateStep, updateNote);
  } finally {
    // Whatever ended it, including a dropped connection: a bar left sitting
    // at some fraction says the update is still running.
    endProgress();
    updateButton.disabled = false;
  }
});

button.addEventListener("click", () => {
  button.disabled = true;
  when.textContent = "Checking...";
  fetch("/update/check", {method: "POST"})
    .then(r => r.json())
    .then(showAbout)
    // A manual check that says nothing when the answer never comes reads as
    // broken, which is the one thing it must not do.
    .catch(() => { when.textContent = UNREACHABLE; })
    .finally(() => { button.disabled = false; });
});
