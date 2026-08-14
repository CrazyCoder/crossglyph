import {form, lineHeightAuto, syncFeatures, syncHyphenation,
        syncLineHeight} from "./dom.js";
import {syncSliders} from "./knobs.js";
import {STORE, attempt, pageControls} from "./remember.js";
import {renderNow, scheduleRender} from "./render.js";
import {refreshReverts} from "./reverts.js";
import {resetAxes} from "./variable.js";

export function resetControl(el) {
  if (el.type === "checkbox") { el.checked = el.defaultChecked; return; }
  if (el.tagName === "SELECT") {
    const declared = [...el.options].find(o => o.defaultSelected) ?? el.options[0];
    if (declared) el.value = declared.value;
    return;
  }
  el.value = el.defaultValue;
}

export function afterReset() {
  syncSliders();
  syncLineHeight();
  syncHyphenation();
  // Resetting the font knobs puts hinting back, and that is half of
  // what decides whether stem darkening can do anything.
  syncFeatures();
  refreshReverts();
  scheduleRender();
}

//: Wired by the entry point rather than on import: renderNow comes from
//: render.js, and a module body can run while a module it imports is still
//: evaluating. The other two are here for company, so one file's buttons are
//: wired in one place.
export function wireResets() {
  // Directly rather than through scheduleRender: this is a deliberate press,
  // and waiting out the coalescing delay would read as the button not working.
  document.getElementById("retry").addEventListener("click", renderNow);

  document.getElementById("reset-font").addEventListener("click", () => {
    // Everything in the Font section: the tuning knobs plus `size`, which
    // posts at the root. The text box is content rather than a knob, so
    // neither button touches it -- an empty box already means "use the
    // shipped sample".
    //
    // The axis controls go back too, but not to the markup: their factory
    // value is the family's own, so resetAxes is what puts them there.
    for (const el of form.elements) {
      if (el.name && el.dataset.group !== "page" && el.dataset.group !== "axes"
          && el.name !== "text") {
        resetControl(el);
      }
    }
    lineHeightAuto.checked = lineHeightAuto.defaultChecked;
    resetAxes();
    afterReset();
  });

  document.getElementById("reset-page").addEventListener("click", () => {
    for (const el of pageControls()) resetControl(el);
    // Forget rather than save today's defaults: "no preference" has to stay
    // distinct from "chose these", or a later change to what the device ships
    // would never reach anyone who had pressed this once.
    attempt(() => localStorage.removeItem(STORE));
    afterReset();
  });
}
