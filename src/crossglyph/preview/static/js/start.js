import {familyPicker} from "./family.js";
import {form, syncHyphenation, syncLineHeight} from "./dom.js";
import {fillPresets, outField, showFallbackState} from "./export.js";
import {syncSliders} from "./knobs.js";
import {loadPage} from "./remember.js";
import {renderNow} from "./render.js";
import {refreshReverts} from "./reverts.js";
import {loadText} from "./text.js";
import {fillFamilies, onFamilyChange} from "./variable.js";

familyPicker.addEventListener("change", onFamilyChange);

loadPage();
loadText();
syncSliders();
syncLineHeight();
syncHyphenation();
refreshReverts();

// Seed the box with the server's sample so it can be edited, not just
// replaced, and fill the picker with what the source folder has.
fetch("/defaults").then(r => r.json()).then(d => {
  form.elements.text.placeholder = d.text;
  fillPresets(d.presets || []);
  showFallbackState(d.fallbacks);
  outField.value = d.out || "";
  outField.placeholder = d.out_resolved || "";
  document.getElementById("source-note").textContent =
    `Fonts come from ${d.source}, and builds go to ${d.out_resolved}. `
    + `A relative path is resolved against the source folder; empty means a `
    + `cpfonts folder inside it.`;
  fillFamilies(d);
  // A remembered font is only known once this lands, so the first page is
  // drawn from here rather than below -- otherwise it would be the startup
  // font every time, replaced a moment later by the one you chose.
  renderNow();
// Whatever went wrong there, the page is still worth drawing: the picker is
// left empty, which posts no family, which is the app's own startup font. It
// is logged rather than swallowed, since a fault in the page's own script
// lands here too and would otherwise look like a server that never answered.
}).catch((error) => { console.error(error); renderNow(); });
