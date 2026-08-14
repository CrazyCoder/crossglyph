// What this install is, in the two places that say so: the version in the top
// strip, and the sentence at the foot of the export panel. One shape fills
// both, from start.js at load and from the button after that.
const strip = document.getElementById("version-strip");
const number = document.getElementById("version-number");
const dot = document.getElementById("version-dot");
const line = document.getElementById("about-line");
const detail = document.getElementById("about-detail");
const when = document.getElementById("checked-when");
const button = document.getElementById("check-now");

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
  // Worth saying when there is something to act on, and when this install
  // could not act on it anyway.
  if (about.available || !about.can_self_update) said.push(about.instruction);
  detail.textContent = said.join(" ");
  when.textContent = checkedLine(about);

  strip.title = [`CrossGlyph ${about.version}`, ...said].join("\n");
}

// Its own button, so this is a handle the module owns rather than a name
// reaching across modules.
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
