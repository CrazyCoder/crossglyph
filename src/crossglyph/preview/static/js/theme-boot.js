// Runs before anything paints, so a viewer whose system is dark never sees a
// light flash on the way in.
(() => {
  let choice = "system";
  try { choice = localStorage.getItem("crossglyph.theme") || "system"; }
  catch (error) { /* storage blocked; system it is */ }
  document.documentElement.dataset.appearance = choice;
  document.documentElement.classList.toggle("dark", choice === "dark" ||
    (choice === "system" &&
     matchMedia("(prefers-color-scheme: dark)").matches));
})();
