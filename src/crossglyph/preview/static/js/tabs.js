// Which panel the column is showing. Only the widths where the export panel
// has folded in beside the knobs have anything to switch: above that the
// stylesheet takes the bar out of the document, and the attribute this writes
// selects nothing. So there is no width to detect here and no listener on the
// window -- the media query is the whole of that decision, and this only ever
// says which of the two the reader last asked for.
const tune = document.getElementById("tab-tune");
const toExport = document.getElementById("tab-export");
const busy = document.getElementById("tab-busy");

function show(which) {
  document.documentElement.dataset.panel = which;
  tune.setAttribute("aria-pressed", String(which === "tune"));
  toExport.setAttribute("aria-pressed", String(which === "export"));
  // Cleared on either press, not only on the one that opens the export panel:
  // the mark means "something happened in there while you were elsewhere", and
  // leaving the panel you watched it happen in is also having seen it.
  busy.hidden = true;
}

tune.addEventListener("click", () => show("tune"));
toExport.addEventListener("click", () => show("export"));
