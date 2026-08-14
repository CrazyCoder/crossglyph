// Whether the page settings are showing. They are the reader's own device
// settings -- set to match the device you are judging against, then left --
// so they fold away, and the fold is remembered: a section somebody closed
// that opens again on the next reload has not saved them anything.
//
// The attribute is on the root and the stylesheet does the folding, which is
// what lets boot.js put it there before the first paint. Nothing here reads a
// width or a mark: the dot on the heading is the rows' own marks, seen through
// the fold by a CSS rule.
import {attempt} from "./remember.js";

export const PAGE_OPEN = "crossglyph.page-open";

const toggle = document.getElementById("page-toggle");

export function showPage(open) {
  document.documentElement.dataset.page = open ? "open" : "closed";
  toggle.setAttribute("aria-expanded", String(open));
  attempt(() => localStorage.setItem(PAGE_OPEN, open ? "yes" : "no"));
}

toggle.addEventListener("click", () => {
  showPage(document.documentElement.dataset.page !== "open");
});

// The root already says which it is, from before the first paint. This is the
// button catching up with it, rather than a second place deciding.
toggle.setAttribute("aria-expanded",
  String(document.documentElement.dataset.page === "open"));
