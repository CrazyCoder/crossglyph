// What this install is, in the two places that say so: the version in the top
// strip, and the sentence at the foot of the export panel. One fetch fills
// both, from start.js.
const strip = document.getElementById("version-strip");
const line = document.getElementById("about-line");
const detail = document.getElementById("about-detail");

// Enough of a commit to recognise, and short enough to sit in a sentence.
const SHORT = 7;

export function showAbout(about) {
  strip.textContent = about.version;
  line.textContent = `CrossGlyph ${about.version}`;

  const said = [];
  if (about.firmware) {
    said.push("Render core built from crosspoint-reader " +
              `${about.firmware.slice(0, SHORT)}.`);
  }
  // Said only when it is worth saying. An ordinary release can update itself,
  // and a line about that on every page is noise.
  if (!about.can_self_update) said.push(about.instruction);
  detail.textContent = said.join(" ");

  strip.title = [`CrossGlyph ${about.version}`, ...said].join("\n");
}
