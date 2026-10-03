// --- Grid Fit -------------------------------------------------------------
// How cleanly the straight strokes of the text on the page sit on the
// device's pixels, as the server measured them from the font it drew with.
// The score belongs to this text: a different text is a different sample,
// so the gain beside the score only compares two pages of the same text.

const line = document.getElementById("grid-fit");
const parts = document.getElementById("grid-fit-parts");
const detail = document.getElementById("grid-fit-detail");

const STYLE_NAMES = ["Regular", "Bold", "Italic", "Bold Italic"];

//: The score of the page before this one, and what it was a score of.
let last = null;

export function hideGridFit() {
  line.hidden = true;
  detail.hidden = true;
  line.setAttribute("aria-expanded", "false");
  last = null;
}

function axis(value) {
  return value === "" || value === null ? "-" : value;
}

function span(className, text) {
  const el = document.createElement("span");
  el.className = className;
  el.textContent = text;
  return el;
}

// The readout as parts, each styled for what it is, and the same thing as
// one sentence for a screen reader, which would otherwise read the parts as
// a row of unrelated numbers.
function show(sentence, ...kids) {
  parts.replaceChildren(span("gf-label", "Grid Fit"), ...kids);
  line.setAttribute("aria-label", sentence);
}

// `get` reads a header from the render's answer. `key` names what the score
// is a score of: the family and the text.
export function showGridFit(get, key) {
  const fit = get("x-grid-fit");
  if (fit === null) {
    hideGridFit();
    return;
  }
  line.hidden = false;
  if (get("x-grid-fit-mono") === "1") {
    show("Grid Fit is not available in mono.", span("gf-none", "not available in mono"));
    detail.textContent = "Mono has no grey, so there is nothing to measure. "
      + "That says nothing about how the strokes line up.";
    last = null;
    return;
  }
  if (fit === "") {
    show("Grid Fit has no straight strokes to measure on this page.",
         span("gf-none", "no straight strokes on this page"));
    detail.textContent = "Put a few lines of ordinary text on the page.";
    last = null;
    return;
  }
  const score = Number(fit);
  const change = last && last.key === key ? score - last.score : 0;
  last = {key, score};
  const sure = get("x-grid-fit-sure") === "1";
  const x = axis(get("x-grid-fit-x")), y = axis(get("x-grid-fit-y"));
  const kids = [span("gf-score", String(score))];
  // With no change the pill keeps its place, empty and unseen, so X and Y
  // stay where they are when one appears.
  kids.push(change
    ? span(`gf-gain ${change > 0 ? "gf-up" : "gf-down"}`,
           `${change > 0 ? "+" : ""}${change}`)
    : span("gf-gain gf-idle", ""));
  const axes = span("gf-axes", "");
  axes.append(span("gf-axis", "X"), span("gf-value", x),
              span("gf-axis", "Y"), span("gf-value", y));
  kids.push(axes);
  if (!sure) kids.push(span("gf-tag", "few letters"));
  show(`Grid Fit ${score}`
       + (change ? `, ${change > 0 ? "up" : "down"} ${Math.abs(change)}` : "")
       + `. X ${x}, Y ${y}.` + (sure ? "" : " Few letters, so the score is rough."),
       ...kids);

  const styles = (get("x-grid-fit-styles") || "").split(",").filter(Boolean)
    .map((pair) => {
      const [style, value] = pair.split(":");
      return `${STYLE_NAMES[Number(style)] ?? style} ${axis(value)}`;
    });
  const letters = get("x-grid-fit-letters") || "0";
  detail.textContent = [
    styles.join(", "),
    `${letters} letters on this page.`,
    sure ? "" : "That is too few for a steady score: add some text.",
  ].filter(Boolean).join(" | ");
}

line.addEventListener("click", () => {
  detail.hidden = !detail.hidden;
  line.setAttribute("aria-expanded", String(!detail.hidden));
});
