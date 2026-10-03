// --- Grid Fit -------------------------------------------------------------
// How cleanly the straight strokes of the text on the page sit on the
// device's pixels, as the server measured them from the font it drew with.
// The score belongs to this text: a different text is a different sample,
// so the change in brackets only compares two pages of the same text.

const line = document.getElementById("grid-fit");
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
    line.textContent = "Grid Fit: not available in mono";
    detail.textContent = "Mono has no grey, so there is nothing to measure. "
      + "That says nothing about how the strokes line up.";
    last = null;
    return;
  }
  if (fit === "") {
    line.textContent = "Grid Fit: no straight strokes on this page";
    detail.textContent = "Put a few lines of ordinary text on the page.";
    last = null;
    return;
  }
  const score = Number(fit);
  const change = last && last.key === key ? score - last.score : 0;
  last = {key, score};
  const sure = get("x-grid-fit-sure") === "1";
  line.textContent = `Grid Fit ${score}`
    + (change ? ` (${change > 0 ? "+" : ""}${change})` : "")
    + ` | X ${axis(get("x-grid-fit-x"))} Y ${axis(get("x-grid-fit-y"))}`
    + (sure ? "" : " | few letters");

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
