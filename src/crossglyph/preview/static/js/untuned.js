import {form, img} from "./dom.js";
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

// And press and hold on the page itself, where the eye already is. The same
// comparison as the button without leaving the thing being compared, which is
// the gesture every photo editor uses for before and after.
//
// A hold is a look rather than a change of state, so whatever the toggle was
// before the press is what comes back: releasing over a page already set to
// untuned must not leave it tuned. Null means no press is in hand.
let heldFrom = null;

export function holdUntuned() {
  if (heldFrom !== null) return;
  heldFrom = comparing();
  if (!heldFrom) toggleCompare();
}

export function releaseUntuned() {
  if (heldFrom === null) return;
  if (!heldFrom && comparing()) toggleCompare();
  heldFrom = null;
}

//: Wired by the entry point rather than on import: `img` belongs to dom.js,
//: and a module body can run while a module it imports is still evaluating.
export function wireUntuned() {
  compare.addEventListener("click", toggleCompare);

  // Backslash is what Lightroom has used for before/after for twenty years.
  // Not while typing in a field, where it is a character.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "\\" || event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }
    const tag = event.target && event.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    event.preventDefault();
    toggleCompare();
  });

  img.addEventListener("pointerdown", (event) => {
    // The left button only: a right-click is a menu, and a middle one is the
    // browser's own. An image is draggable and text is selectable, either of
    // which swallows the release and leaves the page stuck untuned.
    if (event.button !== 0) return;
    event.preventDefault();
    holdUntuned();
  });
  // Leaving counts as letting go: a press dragged off the sheet gets no
  // pointerup here, and there is no state worth keeping for a gesture that
  // has left.
  for (const kind of ["pointerup", "pointercancel", "pointerleave"]) {
    img.addEventListener(kind, releaseUntuned);
  }
}
