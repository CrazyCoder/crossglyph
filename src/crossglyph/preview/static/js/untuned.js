import {form} from "./dom.js";
import {bypassKnob, factoryState, knobModified, refreshReverts, restoreKnob, reverts, stashed} from "./reverts.js";

// --- comparing the whole tuning -------------------------------------------
// The same toggle over every font knob at once: what does this face look like
// before I touched it? Size is deliberately not in it. It is not tuning -- it
// is which size you are working at -- and 13 is this page's default rather
// than anything the device believes, so dropping to it would change the whole
// page and make the comparison say nothing.
export const UNTUNED_SKIP = new Set(["size"]);
export const compare = document.getElementById("compare");

export function comparing() {
  return compare.getAttribute("aria-pressed") === "true";
}

export function toggleCompare() {
  const on = !comparing();
  compare.setAttribute("aria-pressed", String(on));
  for (const button of reverts) {
    const name = button.dataset.reset;
    if (UNTUNED_SKIP.has(name)) continue;
    if (form.elements[name].dataset.group === "page") continue;
    if (on) {
      // Against factory, not against the config: untuned answers "what did
      // this face look like before anyone touched it", which includes what
      // the .conf has been saying for months.
      if (knobModified(name, factoryState(name)) && !stashed.has(name)) {
        bypassKnob(name, factoryState(name));
      }
    } else {
      restoreKnob(name);
    }
  }
  refreshReverts();
}

compare.addEventListener("click", toggleCompare);

// Backslash is what Lightroom has used for before/after for twenty years. Not
// while typing in a field, where it is a character.
document.addEventListener("keydown", (event) => {
  if (event.key !== "\\" || event.ctrlKey || event.metaKey || event.altKey) return;
  const tag = event.target && event.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  event.preventDefault();
  toggleCompare();
});
