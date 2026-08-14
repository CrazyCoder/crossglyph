// Which sections are open. Both of them -- the page settings and the second
// family -- are things you set once and leave, where the rows around them are
// what a session is actually for, so they fold and start folded. The fold is
// remembered: one that opens again on the next reload has saved nobody
// anything.
//
// The open ones are named in an attribute on the root and the stylesheet does
// the folding, which is what lets boot.js put it there before the first paint.
// A list rather than one attribute apiece so there is a single thing to write
// down, and `[data-folds~="page"]` is how a rule asks about one of them.
import {attempt} from "./remember.js";

export const FOLDS = "crossglyph.folds";

const toggles = [...document.querySelectorAll("[data-fold]")];

function open() {
  const said = document.documentElement.dataset.folds || "";
  return new Set(said.split(" ").filter(Boolean));
}

export function showFolds(names) {
  const said = [...names].join(" ");
  document.documentElement.dataset.folds = said;
  for (const toggle of toggles) {
    toggle.setAttribute("aria-expanded",
                        String(names.has(toggle.dataset.fold)));
  }
  attempt(() => localStorage.setItem(FOLDS, said));
}

for (const toggle of toggles) {
  toggle.addEventListener("click", () => {
    const names = open();
    const name = toggle.dataset.fold;
    if (!names.delete(name)) names.add(name);
    showFolds(names);
  });
  // The root already says which are open, from before the first paint. This is
  // the button catching up with it, rather than a second place deciding.
  toggle.setAttribute("aria-expanded", String(open().has(toggle.dataset.fold)));
}
