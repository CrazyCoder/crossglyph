// The two things that have to be on the root before anything paints: which
// appearance to draw in, so a viewer whose system is dark never sees a light
// flash on the way in, and which foldable sections are open, so one somebody
// closed does not open and shut again on every reload.
//
// Both are read here rather than by the modules that own them because a module
// runs after the first paint, which is exactly too late for either.
(() => {
  const remembered = (key, fallback) => {
    try { return localStorage.getItem(key) || fallback; }
    catch (error) { return fallback; }  // storage blocked; the default it is
  };

  const choice = remembered("crossglyph.theme", "system");
  document.documentElement.dataset.appearance = choice;
  document.documentElement.classList.toggle("dark", choice === "dark" ||
    (choice === "system" &&
     matchMedia("(prefers-color-scheme: dark)").matches));

  // Named one by one, and folded unless named. Both of these are settings
  // somebody reaches for rarely, where the rows around them are what a session
  // is actually for.
  document.documentElement.dataset.folds = remembered("crossglyph.folds", "");
})();
