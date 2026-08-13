import {attempt} from "./remember.js";

// --- appearance -----------------------------------------------------------
// Three states, not two: "system" has to stay reachable, or someone who picks
// light once can never get back to following their machine.
export const THEME = "crossglyph.theme";
export const themeButtons = [...document.querySelectorAll("#theme button")];
export const systemDark = matchMedia("(prefers-color-scheme: dark)");

export function applyAppearance(choice, remember) {
  document.documentElement.dataset.appearance = choice;
  document.documentElement.classList.toggle("dark",
    choice === "dark" || (choice === "system" && systemDark.matches));
  for (const button of themeButtons) {
    button.setAttribute("aria-pressed",
      String(button.dataset.appearance === choice));
  }
  if (remember) attempt(() => localStorage.setItem(THEME, choice));
}

for (const button of themeButtons) {
  button.addEventListener("click",
    () => applyAppearance(button.dataset.appearance, true));
}
// Following the system means following it as it changes, not only at load.
systemDark.addEventListener("change", () => {
  if (document.documentElement.dataset.appearance === "system") {
    applyAppearance("system", false);
  }
});
applyAppearance(document.documentElement.dataset.appearance || "system", false);
