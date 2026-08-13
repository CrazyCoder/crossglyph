import {familyPicker} from "./family.js";
import {form, samplePicker, syncHyphenation, syncLineHeight} from "./dom.js";
import {fillPresets, outField, showFallbackState,
        wireBuildButtons} from "./export.js";
import {syncSliders, wireKnobs} from "./knobs.js";
import {declareLanguage, loadPage, preferredLanguage} from "./remember.js";
import {renderNow, scheduleRender, wireRender} from "./render.js";
import {wireResets} from "./resets.js";
import {refreshReverts} from "./reverts.js";
import {fillSamples, loadText, restoreSample, sampleChosen} from "./text.js";
import {wireUntuned} from "./untuned.js";
import {fillFamilies, onFamilyChange} from "./variable.js";

// Every listener that reaches across modules, in one place and after all of
// them have finished evaluating. The import graph has cycles, so a module body
// runs while a module it imports may still be on its way up, and a binding
// read there is in its dead zone. A module still wires handles of its own,
// which cannot be.
wireKnobs();
wireRender();
wireResets();
wireUntuned();
wireBuildButtons();
familyPicker.addEventListener("change", onFamilyChange);
samplePicker.addEventListener("change", () => { sampleChosen(); scheduleRender(); });

const remembered = loadPage();
// Nothing has been set on this device, so the browser's own languages are the
// best guess there is at which patterns to hyphenate with. Declared rather
// than saved, so it stays a default and not a decision -- see declareLanguage.
if (!remembered) declareLanguage(preferredLanguage(navigator.languages));
loadText();
syncSliders();
syncLineHeight();
syncHyphenation();
refreshReverts();

// Seed the box with the server's sample so it can be edited, not just
// replaced, and fill the picker with what the source folder has.
fetch("/defaults").then(r => r.json()).then(d => {
  form.elements.text.placeholder = d.text;
  // The presets, and which of them the box opens on. Before this lands the
  // picker holds Custom alone, which is why the box is filled from here.
  fillSamples(d.samples);
  restoreSample(navigator.languages);
  fillPresets(d.presets || [], d.base || []);
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
