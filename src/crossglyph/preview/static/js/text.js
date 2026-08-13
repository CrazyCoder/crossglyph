import {form} from "./dom.js";
import {attempt} from "./remember.js";

// --- the sample text ------------------------------------------------------
// Kept apart from the page settings: it is what you are looking at rather than
// a setting of the reader's, so neither reset button throws it away. Emptying
// the box forgets it, which is also how you get the shipped sample back.
export const TEXT = "crossglyph.text";

export function saveText() {
  const value = form.elements.text.value;
  attempt(() => value ? localStorage.setItem(TEXT, value)
                      : localStorage.removeItem(TEXT));
}

export function loadText() {
  const saved = attempt(() => localStorage.getItem(TEXT), null);
  if (saved) form.elements.text.value = saved;
}
