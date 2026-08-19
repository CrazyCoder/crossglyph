// The Page knobs and view size persist to localStorage, and the ways that
// breaks are all silent: a setting that stops being remembered, a stored value
// that blanks a control, storage throwing in a private window. None is an error.
//
// Driven from tests/test_preview.py, which skips when node is absent. The page
// has no build step and no framework, so this stubs the handful of browser
// globals its script touches and runs the real source out of index.html --
// there is no second copy of the logic to drift.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));

const STATIC = join(here, "..", "src", "crossglyph", "preview", "static");
const JS = join(STATIC, "js");

// The entry, and the modules it pulls in. Each block below wants a page whose
// state is fresh, and an import is cached for the life of the process, so the
// graph is built again per block inside a context of its own -- as modules,
// linked and evaluated the way the browser does it. Running them concatenated
// into one scope would be simpler and would test the wrong thing: every name
// resolves in one scope, so a module reading a name it never imported passes
// here and throws on the first click over there.
const ENTRY = "app.js";
const files = new Map();
function fileFor(name) {
  if (!files.has(name)) files.set(name, readFileSync(join(JS, name), "utf8"));
  return files.get(name);
}
const sources = [...fileFor(ENTRY).matchAll(/^import "\.\/([\w.-]+)";$/gm)]
  .map(([, name]) => ({ name, text: fileFor(name) }));

// Node's own globals, which a fresh context does not have. The stubs a block
// wants to look at afterwards go in beside these, in makeEnv.
const HOST = { setTimeout, clearTimeout, setInterval, clearInterval, console,
               performance, URL, AbortController, TextDecoder };

async function evaluatePage(sandbox) {
  const context = vm.createContext(sandbox);
  const built = new Map();
  const moduleFor = (name) => {
    if (!built.has(name)) {
      built.set(name, new vm.SourceTextModule(fileFor(name),
                                              { identifier: name, context }));
    }
    return built.get(name);
  };
  const entry = moduleFor(ENTRY);
  await entry.link(specifier => moduleFor(specifier.replace("./", "")));
  await entry.evaluate();
  // What each module exports, so a helper that is pure arithmetic can be
  // asked directly rather than through a screen built to provoke it.
  return new Map([...built].map(([name, module]) => [name, module.namespace]));
}

// --- the split itself ------------------------------------------------------
// Linking catches a borrowed name on the line that runs it, which leaves the
// lines no block reaches. Those are a text question rather than a run-time one,
// so they are read: a name another module owns, used without importing it.
const WORD = /[A-Za-z_$][\w$]*/g;

// Comments and string bodies are not code -- a name in prose, or in a CSS
// selector, is not a use of it. A template's ${...} is code and stays.
function code(text) {
  let out = "", at = 0;
  const upTo = (end) => { const from = at; at = end; return text.slice(from, at); };
  while (at < text.length) {
    const two = text.slice(at, at + 2);
    if (two === "//") { while (at < text.length && text[at] !== "\n") at++; continue; }
    if (two === "/*") {
      at = text.indexOf("*/", at + 2);
      at = at < 0 ? text.length : at + 2;
      continue;
    }
    const quote = text[at];
    if (quote === '"' || quote === "'") {
      at++;
      while (at < text.length && text[at] !== quote) at += text[at] === "\\" ? 2 : 1;
      at++;
      out += " ";
      continue;
    }
    if (quote === "`") {
      at++;
      while (at < text.length && text[at] !== "`") {
        if (text[at] === "\\") { at += 2; continue; }
        if (text.slice(at, at + 2) === "${") {
          at += 2;
          let depth = 1, from = at;
          while (at < text.length && depth) {
            if (text[at] === "{") depth++;
            else if (text[at] === "}" && !--depth) break;
            at++;
          }
          out += " " + text.slice(from, at) + " ";
          at++;
          continue;
        }
        at++;
      }
      at++;
      out += " ";
      continue;
    }
    out += upTo(at + 1);
  }
  return out;
}

// Every name a file binds for itself: declarations, parameters, catch and
// import lists. Deliberately generous -- a name it binds anywhere is a name it
// is not borrowing, and erring that way costs a miss rather than a false alarm.
function bound(text) {
  const names = new Set();
  const all = (list) => { for (const word of list.match(WORD) || []) names.add(word); };
  for (const [, one] of text.matchAll(
      /(?:const|let|var|function|class)\s+([\w$]+)/g)) names.add(one);
  for (const [, one] of text.matchAll(/(?:^|[^\w$.])([\w$]+)\s*=>/g)) names.add(one);
  for (const [, list] of text.matchAll(
      /(?:const|let|var)\s*(\{[^}]*\}|\[[^\]]*\])/g)) all(list);
  for (const [, list] of text.matchAll(/\(([^()]*)\)\s*(?:=>|\{)/g)) all(list);
  for (const [, list] of text.matchAll(/import\s*\{([^}]*)\}/g)) all(list);
  return names;
}

// And every name it reads. Property reads and object keys are not free names:
// `el.form` and `{form: x}` say nothing about what the file imported. A dot
// after a dot is a spread rather than a property, and `...form` is a use.
function borrowed(text) {
  return new Set(code(text)
    .replace(/(?<!\.)\.\s*[\w$]+/g, " ")
    .replace(/(^|[{,])\s*[\w$]+\s*:/gm, "$1 ")
    .match(WORD) || []);
}

// What each name belongs to, so a complaint can name the file to import from.
const exported = new Map();
for (const { name, text } of sources) {
  for (const [, one] of text.matchAll(
      /^export\s+(?:async\s+)?(?:function|const|let|class)\s+([\w$]+)/gm)) {
    exported.set(one, name);
  }
}

// defaultValue / defaultChecked / defaultSelected are what the two reset
// buttons restore from, so the stub has to carry them the way a real control
// does: the value the markup declared, fixed at construction.
function makeControl({ name, type = "text", value = "", checked = false, group,
                      options, min = "", max = "", step = "1", coarse }) {
  const el = { name, type, value, checked, dataset: {}, options, min, max, step };
  // What a shifted press moves this knob by, which the markup declares beside
  // the step. A stub without it would take the derived one a font's own axis
  // gets, and the two answer differently on every knob here.
  if (coarse) el.dataset.coarse = coarse;
  el.defaultValue = value;
  el.defaultChecked = checked;
  // A checkbox carries "on" whether or not the markup gives it a value, while
  // defaultValue reflects the attribute and so stays empty. The two differ in
  // every browser and none of these boxes sets one, so anything comparing them
  // has to face that here rather than only on the page.
  if (type === "checkbox") {
    el.value = "on";
    el.defaultValue = "";
  }
  if (group) el.dataset.group = group;
  if (options) {
    el.tagName = "SELECT";
    // A <select> has no `checked` at all, and code that reads it raw gets
    // undefined rather than false. Mirrored, because that difference is worth
    // exactly one bug: two selects marked as changed on a page nobody touched.
    delete el.checked;
    delete el.defaultChecked;
    // And it refuses a value none of its options carries, which is the whole
    // reason the page has to offer a config's own value before applying it.
    let current = value;
    Object.defineProperty(el, "value", {
      get: () => current,
      set: (next) => {
        current = el.options.some(option => option.value === next) ? next : "";
      },
    });
    const own = (option) => {
      option.dataset = option.dataset || {};
      option.remove = () => {
        el.options.splice(el.options.indexOf(option), 1);
      };
      return option;
    };
    el.add = (option) => el.options.push(own(option));
    // Refilling a select drops what it was showing: a real one blanks when the
    // value it held is no longer among its options.
    el.replaceChildren = (...next) => {
      el.options = next.map(own);
      el.value = "";
    };
    for (const option of options) {
      own(option).defaultSelected = option.value === value;
    }
  }
  el.parentElement = { querySelector: () => null };
  // A control can be listened to directly, not only through its form: the text
  // box belongs to the knob form by `form="knobs"` while sitting outside it in
  // the DOM, and nothing it fires reaches the form's own listener.
  el.on = {};
  el.addEventListener = (kind, fn) => { el.on[kind] = fn; };
  return el;
}

// What /defaults answers. The picker is built from it, so a test that changes
// what the folder holds changes this rather than the page.
// What /update answers with. A release that can update itself, on the newest
// version there is, so a block only says what it is changing.
const ABOUT = {
  version: "1.2.3", firmware: "45caec3e76c2472b", kind: "zip",
  home: "https://github.com/CrazyCoder/crossglyph",
  can_self_update: true, notice: "",
  latest: "1.2.3", available: null, checked_at: 1000, checking_off: false,
  error: null,
};

const DEFAULTS = {
  text: "Съешь ещё этих мягких французских булок.",
  // A few presets, keyed and ordered as /defaults serves them. Short on
  // purpose: what is under test is the choosing and the remembering, not the
  // prose. Simplified Chinese is here for the script-not-country rule, and
  // Japanese because it has no hyphenation patterns to follow.
  samples: {
    "zh-Hans": { name: "简体中文", text: "天地玄黄。\nThe quick brown fox." },
    en: { name: "English", text: "The quick brown fox.\nAll human beings." },
    de: { name: "Deutsch", text: "Victor jagt zwölf Boxkämpfer.\nAlle Menschen." },
    ja: { name: "日本語", text: "いろはにほへと\nすべての人間は。" },
    ru: { name: "Русский", text: "Съешь ещё этих булок.\nВсе люди." },
  },
  font: "Alto-Medium.otf",
  faces: ["bold", "regular"],
  families: [
    { name: "Sample", faces: ["bold", "italic", "regular"],
      conf: "sample.conf", derived: false,
      tuning: { gamma: 1, weight: 0, hinting: "normal",
                thresholds: [2, 5, 9], line_height: null },
      outlines: "cff",
      features: { ligatures: true, figures: true },
      bytecode: false, tricky: false,
      export: { name: "Sample", sizes: "12 14 16 18", sizes_mod: "", mod_suffix: "Mod",
                intervals: "reading", ranges: "",
                fallbacks: true, fallback1: "", fallback2: "" } },
    // A variable family: two files, four slots, and the weights the font's own
    // instances put them at.
    { name: "Vari", faces: ["bold", "bolditalic", "italic", "regular"],
      conf: "vari.conf", derived: false,
      tuning: { gamma: 1, weight: 0, hinting: "normal",
                thresholds: [4, 8, 12], line_height: null },
      variable: {
        axes: [{ tag: "wght", min: 300, default: 300, max: 900 },
               { tag: "wdth", min: 87, default: 100, max: 112 }],
        instances: [{ name: "Light", wght: 300 }, { name: "Regular", wght: 400 },
                    { name: "Bold", wght: 700 }, { name: "Black", wght: 900 }],
        weights: { text: 400, bold: 700 },
        other: { wdth: 100 },
      },
      outlines: "truetype",
      features: { ligatures: true, figures: true },
      // TrueType with nothing for the interpreter to run, which is what the
      // bundled Literata is: a stub `prep` and no instructions, so FreeType
      // fits it with the auto-hinter instead.
      bytecode: false, tricky: false,
      export: { name: "Vari", sizes: "12 14 16 18", sizes_mod: "", mod_suffix: "Mod",
                intervals: "reading", ranges: "",
                fallbacks: false, fallback1: "", fallback2: "" } },
    // Alto is set to something in its config, which is what the knobs have
    // to open at and what their arrows compare against.
    { name: "Alto", faces: ["bold", "regular"],
      conf: "alto.conf", derived: false,
      tuning: { gamma: 1.2, weight: 0.1, hinting: "normal",
                thresholds: [3, 6, 10], line_height: null },
      outlines: "truetype",
      features: { ligatures: false, figures: false },
      bytecode: true, tricky: false,
      export: { name: "Alto", sizes: "12 13", sizes_mod: "", mod_suffix: "Mod",
                intervals: "reading,cyrillic", ranges: "",
                fallbacks: false, fallback1: "Sample", fallback2: "" } },
  ],
  family: "Alto",
  // Where the bundled faces are, if anywhere: empty means the panel offers
  // to fetch them.
  fallbacks: "D:\fonts\fallbacks",
  source: "D:\\fonts",
  out: "",
  // The ranges are what the panel works containment out from, so the fixture
  // carries the shape the real ones have: `reading` swallows `default` whole,
  // and only half of `cyrillic`, which is why one of those can be settled by
  // ticking it and the other cannot.
  presets: [{ name: "reading", label: "Reading", note: "Fiction",
              ranges: [[0x0080, 0x024F], [0x0370, 0x03FF], [0x0400, 0x04FF]] },
            { name: "default", label: "Default", note: "CrossPoint",
              ranges: [[0x0080, 0x017F], [0x0400, 0x04FF]] },
            { name: "cyrillic", label: "Cyrillic", note: "",
              ranges: [[0x0400, 0x04FF], [0x0500, 0x052F]] },
            { name: "greek", label: "Greek", note: "",
              ranges: [[0x0370, 0x03FF], [0x1F00, 0x1FFF]] }],
  base: [[0x0000, 0x007F], [0x2000, 0x206F]],
};

// What POST /save answers with. The page takes its new baseline from this
// rather than from what it sent, since the writer decides what is stored.
const SAVED = {
  conf: "alto.conf", moved: ["gamma"],
  tuning: { gamma: 2, weight: 0.1, hinting: "normal", line_height: null },
};

// A <select> the script fills itself, which the form's stub controls are not:
// it starts empty, options arrive through add(), and the first one to land is
// the selected one until something says otherwise.
function makeSelect() {
  const el = {
    options: [],
    on: {},
    _value: "",
    add(option) {
      el.options.push(option);
      if (el.options.length === 1) el._value = option.value;
    },
    get value() { return el._value; },
    // A real select refuses a value none of its options carries -- it blanks
    // instead. Mirrored here, so a regression that posted a family the folder
    // no longer has fails the probe rather than passing on a lenient stub.
    set value(next) {
      el._value = el.options.some(option => option.value === next) ? next : "";
    },
    get selectedOptions() {
      return el.options.filter(option => option.value === el._value);
    },
    replaceChildren(...options) { el.options = options; el._value = ""; },
    addEventListener(kind, fn) { el.on[kind] = fn; },
    choose(next) { el.value = next; el.on.change(); },
  };
  return el;
}

// Enough of an element for the two places the page builds DOM itself: the
// style badges and the coverage checkboxes.
function makeElement() {
  return {
    dataset: {}, textContent: "", title: "", className: "",
    // The fill behind a slider's thumb is a custom property, so a built row
    // sets one the moment it is shown.
    style: { props: {}, setProperty(key, value) { this.props[key] = value; } },
    type: "", value: "", checked: false, children: [], hidden: false,
    disabled: false,
    min: "", max: "", step: "", tabIndex: 0, inputMode: "", id: "",
    htmlFor: "", on: {}, parentElement: null,
    attrs: {},
    classes: new Set(),
    get classList() {
      const owner = this;
      return {
        add: (name) => owner.classes.add(name),
        remove: (name) => owner.classes.remove(name),
        contains: (name) => owner.classes.has(name),
        toggle: (name, on) => (on ? owner.classes.add(name)
                                  : owner.classes.delete(name)),
      };
    },
    // A child knows its parent, as one does: the coverage row reaches the
    // label from the box inside it to say the tick is carried rather than
    // chosen.
    append(...kids) {
      for (const kid of kids) if (kid) kid.parentElement = this;
      this.children.push(...kids);
    },
    setAttribute(key, value) { this.attrs[key] = value; },
    getAttribute(key) { return this.attrs[key]; },
    // Elements the page builds itself are listened to as it builds them --
    // the axis sliders are wired at that moment and never found again.
    addEventListener(kind, fn) { this.on[kind] = fn; },
    replaceChildren(...kids) { this.children = kids; },
  };
}

// A family carrying more sizes than the four steps, which is what a CJK one
// does: 8, 10 and 12 are the sizes the interface borrows it at. `mod` does the
// same to the second family, whose overflow has nowhere else to go either.
function sixSizes(key = "sizes") {
  const defaults = structuredClone(DEFAULTS);
  const alto = defaults.families.find(one => one.name === "Alto");
  alto.export[key] = "8 10 12 14 16 18";
  return defaults;
}

function makeEnv(storage, defaults = DEFAULTS, opts = {}) {
  // A copy per run: the page keeps what /defaults hands it and writes back
  // into it on save, so sharing the fixture would leak one block's save into
  // every block after it.
  defaults = structuredClone(defaults);
  const controls = [
    // The render core changes geometry with the reader model. It belongs to
    // the Page form even though the device panel owns and displays it.
    makeControl({
      name: "device", value: "x4", group: "page",
      options: [{ value: "x4" }, { value: "x3" }],
    }),
    makeControl({ name: "size", type: "number", value: "13", group: "root",
                  min: "6", max: "40", step: "0.25", coarse: "1" }),
    makeControl({ name: "gamma", type: "number", value: "1",
                  min: "0.3", max: "4", step: "0.05", coarse: "0.5" }),
    // A second font knob, so "the save carries the whole panel rather than
    // only what changed" is a claim this can actually tell apart.
    makeControl({ name: "weight", type: "number", value: "0",
                  min: "-1", max: "1", step: "0.05", coarse: "0.25" }),
    makeControl({ name: "margin", type: "number", value: "5", group: "page",
                  min: "5", max: "40", step: "1", coarse: "5" }),
    makeControl({
      name: "alignment", value: "justify", group: "page",
      options: [{ value: "justify" }, { value: "left" }, { value: "center" }],
    }),
    // Every language the core has patterns for, as the markup lists them, and
    // English declared as the markup declares it. The real list matters here:
    // a shorter one would take a value it has no option for and blank, so a
    // detection test could pass against a control that cannot hold its answer.
    makeControl({
      name: "language", value: "en", group: "page",
      options: [{ value: "en" }, { value: "fi" }, { value: "fr" },
                { value: "de" }, { value: "it" }, { value: "pl" },
                { value: "ru" }, { value: "es" }, { value: "sv" },
                { value: "uk" }, { value: "" }],
    }),
    // A font-side select, so the baseline machinery is exercised on the kind
    // of control that has no `checked` to compare.
    makeControl({
      name: "hinting", value: "normal",
      options: [{ value: "normal" }, { value: "light" },
                { value: "none" }, { value: "auto" }],
    }),
    // Two presets in the markup; a config carrying its own triple has to be
    // offered as a third rather than blanking the control.
    makeControl({
      name: "thresholds", value: "4,8,12",
      options: [{ value: "4,8,12" }, { value: "3,6,10" }],
    }),
    // Greyed by the hinting row above rather than by the font alone.
    makeControl({ name: "stem_darkening", type: "checkbox", checked: false }),
    // Greyed by the hinting row and by two facts about the face.
    makeControl({ name: "grayscale_hinting", type: "checkbox", checked: false }),
    // Greys the two coverage knobs above when it is on.
    makeControl({ name: "mono", type: "checkbox", checked: false }),
    // A font-side checkbox, so the reverts are exercised on the kind of
    // control whose whole state is `checked`. It is also one of the two the
    // font itself can grey out.
    makeControl({ name: "ligatures", type: "checkbox", checked: true }),
    makeControl({
      name: "figures", value: "default",
      options: [{ value: "default" }, { value: "proportional" }],
    }),
    makeControl({ name: "hyphenation", type: "checkbox", checked: false, group: "page" }),
    makeControl({ name: "antialiased", type: "checkbox", checked: true, group: "page" }),
    makeControl({ name: "inverted", type: "checkbox", checked: false, group: "page" }),
    makeControl({ name: "line_height", type: "number", value: "1.15",
                  min: "0.8", max: "2.2", step: "0.05", coarse: "0.25" }),
    makeControl({ name: "text", value: "", group: "root" }),
    // The two variable-font weight pickers. They start empty: their options
    // come from whichever family is showing, and a static one has none.
    makeControl({ name: "axis_text", value: "", group: "axes", options: [] }),
    makeControl({ name: "axis_bold", value: "", group: "axes", options: [] }),
  ];
  const byName = Object.fromEntries(controls.map(c => [c.name, c]));
  const listeners = {};
  // Each numeric knob is a slider and a field showing one value, so the stub
  // carries the sliders too: "the slider moved but the field did not" is a
  // failure you would have to catch by eye otherwise.
  const sliderList = ["size", "gamma", "margin", "line_height"].map(name => ({
    dataset: { sliderFor: name },
    value: byName[name].value,
    min: byName[name].min,
    max: byName[name].max,
    disabled: false,
    // The filled part of the track is how a slider says it is live and where
    // it sits, so the stub records it rather than discarding it.
    style: { props: {}, setProperty(key, value) { this.props[key] = value; } },
    addEventListener(kind, fn) { if (kind === "input") this.fire = fn; },
  }));
  // The steppers, so the +/- path can be driven -- it reaches setField without
  // ever firing an input event, which is its own class of bug.
  const stepList = ["size", "gamma", "margin"].flatMap(
    name => [-1, 1].map(dir => ({
      dataset: { for: name, dir: String(dir) },
      on: {},
      addEventListener(kind, fn) { this.on[kind] = fn; },
      press(shiftKey = false) { this.on.pointerdown({ shiftKey }); },
    })));
  // One arrow per knob, shown only when that knob is off its default.
  // A checkbox on each side of the font/page line, because a checkbox's state
  // is `checked` alone and everything else about it is a trap.
  const revertList = ["size", "gamma", "margin", "alignment", "line_height",
                      "hinting", "language"].map(name => ({
    dataset: { reset: name },
    hidden: true,
    on: {},
    addEventListener(kind, fn) { this.on[kind] = fn; },
    click() { this.on.click(); },
  }));
  // A checkbox knob carries a mark instead: it says the knob differs and from
  // what, and offers no press, a switch being its own way back.
  const markList = ["ligatures", "hyphenation", "mono"].map(name => ({
    dataset: { mark: name },
    hidden: true,
    title: "",
  }));
  const form = {
    elements: Object.assign(controls, byName),
    addEventListener: (kind, fn) => { listeners[kind] = fn; },
    querySelectorAll: (selector) => {
      if (selector === "[data-slider-for]") return sliderList;
      if (selector === ".revert") return revertList;
      if (selector === ".mark") return markList;
      if (selector === "button.step") return stepList;
      const named = [...selector.matchAll(/data-(?:slider-)?for="([\w_]+)"/g)]
        .map(m => m[1]);
      // Sliders and steppers both: the page greys a knob by walking every
      // control that drives it, and a stub that returned only one of them
      // would let half of that go untested.
      return named.length
        ? [...sliderList.filter(s => named.includes(s.dataset.sliderFor)),
           ...stepList.filter(s => named.includes(s.dataset.for))] : [];
    },
  };
  const clicks = {};
  const button = id => ({
    addEventListener: (kind, fn) => { if (kind === "click") clicks[id] = fn; },
  });
  const family = makeSelect();
  // The sample picker is not empty in the markup: Custom is declared there, so
  // a page whose /defaults never answered still has an entry to sit on.
  const sample = makeSelect();
  sample.add({ value: "", textContent: "Custom" });
  const exportFields = {
    // A box per step, one more for whatever a config carries beyond them, and
    // the same four again for the second family the same faces can build.
    size1: { value: "" }, size2: { value: "" }, size3: { value: "" },
    size4: { value: "" }, size_more: { value: "" },
    mod1: { value: "" }, mod2: { value: "" }, mod3: { value: "" },
    mod4: { value: "" }, mod_more: { value: "" },
    mod_suffix: { value: "", disabled: false },
    // Beside the heading rather than in the panel's grid, but a control of the
    // same form: what the family is called once it is built.
    name: { value: "" },
    ranges: { value: "" },
    // The wrapper is real markup: the label sits beside this box rather than
    // around it, so what gets marked when the page needs it is the span the
    // two share.
    fallbacks: { type: "checkbox", checked: false,
                 parentElement: makeElement() },
    fallback1: makeSelect(), fallback2: makeSelect(),
    // The output folder saves itself when it loses focus, so it listens.
    out: { value: "", on: {},
           addEventListener(kind, fn) { this.on[kind] = fn; },
           leave() { return this.on.change(); } },
  };
  // Every element in a document has a dataset, empty or not, and the page is
  // entitled to read one off whatever it was handed: a stub without it turns a
  // working line into "cannot read properties of undefined".
  for (const [name, field] of Object.entries(exportFields)) {
    field.dataset = field.dataset || {};
    field.name = field.name || name;
  }
  // The title above each size box. A press rather than a label: it moves the
  // size knob to what its box holds.
  const sizeTitles = ["size1", "size2", "size3", "size4",
                      "mod1", "mod2", "mod3", "mod4"].map(name => ({
    dataset: { previewSize: name },
    on: {},
    addEventListener(kind, fn) { this.on[kind] = fn; },
  }));
  const exportForm = {
    hidden: false, elements: exportFields, on: {},
    addEventListener(kind, fn) { this.on[kind] = fn; },
    querySelectorAll: (selector) =>
      selector === "[data-preview-size]" ? sizeTitles : [],
    //: Pressing a box's title, which shows the page at the size it holds.
    preview(name) {
      sizeTitles.find(title => title.dataset.previewSize === name).on.click();
    },
    // What the page listens for: a change to any control in here offers a save.
    edit(field) { this.on.input({ target: exportFields[field] }); },
    // And leaving one, which is when a size box snaps to the quarter point.
    leave(field) { this.on.change({ target: exportFields[field] }); },
  };
  const presetList = {
    children: [],
    replaceChildren(...kids) { this.children = kids; },
    querySelectorAll: () => presetList.children.flatMap(
      label => label.children.filter(kid => kid.type === "checkbox")),
  };
  const buildButtons = {};
  // Every value `disabled` took, in order: "out while it runs, back when it
  // finishes" is a sequence, and reading the property afterwards only ever
  // shows the end of it.
  const buildButton = (id, label = "") => ({
    states: [],
    textContent: label,
    // A button can be marked as the move the page is waiting on, the way a
    // tick can, so it carries the same classes any element does.
    classes: new Set(),
    get classList() {
      const owner = this;
      return {
        add: (name) => owner.classes.add(name),
        remove: (name) => owner.classes.delete(name),
        contains: (name) => owner.classes.has(name),
        toggle: (name, on) => (on ? owner.classes.add(name)
                                  : owner.classes.delete(name)),
      };
    },
    _disabled: false,
    get disabled() { return this._disabled; },
    set disabled(next) { this._disabled = next; this.states.push(next); },
    // Wrapped so a press carries an event, as every real one does: the build
    // buttons read shiftKey off it, and a handler called bare saw undefined.
    addEventListener(kind, fn) {
      if (kind === "click") buildButtons[id] = (event = {}) => fn(event);
    },
  });
  // A text holder that remembers everything it was set to.
  const recording = () => ({
    steps: [],
    _text: "",
    get textContent() { return this._text; },
    set textContent(next) { this._text = next; this.steps.push(next); },
  });
  // A progress row: the rule that fills and the line under it, reached the way
  // the module reaches them, by class inside the row it was handed. Two of
  // these exist -- the build's and the update's -- and every value each part
  // took is kept, since "it counted its way there" is a sequence and reading
  // the property afterwards only shows where it stopped.
  const progressRow = () => {
    const bar = {
      attrs: {}, classes: new Set(),
      classList: {
        add(name) { bar.classes.add(name); },
        remove(name) { bar.classes.delete(name); },
      },
      setAttribute(name, value) { this.attrs[name] = value; },
      removeAttribute(name) { delete this.attrs[name]; },
    };
    const fill = { widths: [], style: {
      _width: "",
      get width() { return this._width; },
      set width(next) { this._width = next; fill.widths.push(next); },
    } };
    const what = recording(), count = recording();
    const parts = { ".bar": bar, ".bar-fill": fill,
                    ".progress-what": what, ".progress-count": count };
    // The build's row is the panel's foot, which is on screen whether or not
    // anything is running and says so with a dataset flag rather than by
    // leaving the document. The update's uses `hidden`; both are here because
    // one stub stands for both rows.
    return { hidden: true, dataset: {}, bar, fill, what, count,
             querySelector(selector) { return parts[selector]; } };
  };
  // A press whose element carries state: the panel tabs and the fold on the
  // Page heading. What the press leaves on the element is asserted as well as
  // what it does, so this keeps the attribute rather than dropping it.
  // Every listener, not the last one: a tab carries two, one from tabs.js for
  // which panel is showing and one from start.js for the marks that depend on
  // it. Kept in the order they were added, which is the order the browser
  // calls them in and the order the second one needs -- it reads what the
  // first one wrote.
  const presses = {};
  const pressStub = (name) => ({
    attrs: {},
    setAttribute(key, value) { this.attrs[key] = value; },
    addEventListener(kind, fn) {
      if (kind === "click") (presses[name] ||= []).push(fn);
    },
  });
  const press = (name) => { for (const fn of presses[name] || []) fn(); };
  const saveButton = {
    hidden: false, disabled: true, textContent: "", title: "",
    on: {},
    addEventListener(kind, fn) { this.on[kind] = fn; },
    click() { return this.on.click(); },
  };
  const deviceModel = byName.device;
  deviceModel.id = "device-model";
  const deviceControl = (control) => {
    control.id = control.id || control.name;
    control.dataset.deviceSetting = "";
    return control;
  };
  deviceControl(deviceModel);
  const deviceColor = deviceControl(makeControl({
    name: "device-color", value: "black",
    options: [{ value: "black" }, { value: "white" }],
  }));
  const deviceFrame = deviceControl(makeControl({
    name: "device-frame-shown", type: "checkbox", checked: true,
  }));
  const deviceScale = deviceControl(makeControl({
    name: "device-scale", value: "pixels",
    options: [{ value: "pixels" }, { value: "device" }, { value: "fit" },
              { value: "custom" }],
  }));
  const devicePaper = deviceControl(makeControl({
    name: "device-paper", type: "number", value: "90", min: "50", max: "100",
    coarse: "5",
  }));
  const deviceInk = deviceControl(makeControl({
    name: "device-ink", type: "number", value: "90", min: "50", max: "100",
    coarse: "5",
  }));
  const deviceCalibration = deviceControl(makeControl({
    name: "device-calibration-range", type: "number", value: "100",
    min: "50", max: "150", step: ".5", coarse: "5",
  }));
  const deviceWarm = deviceControl(makeControl({
    name: "device-warm", type: "number", value: "3",
    min: "-12", max: "12", step: ".5", coarse: "2",
  }));
  const deviceTint = deviceControl(makeControl({
    name: "device-tint", type: "number", value: "2.5",
    min: "-8", max: "8", step: ".5", coarse: "2",
  }));
  const deviceSlider = (id, field) => ({
    id, dataset: {sliderFor: field.id}, value: field.value,
    min: field.min, max: field.max, step: field.step,
    style: {props: {}, setProperty(key, value) { this.props[key] = value; }},
    addEventListener(kind, fn) { if (kind === "input") this.fire = fn; },
  });
  const devicePaperSlider = deviceSlider("device-paper-slider", devicePaper);
  const deviceInkSlider = deviceSlider("device-ink-slider", deviceInk);
  const deviceCalibrationSlider =
    deviceSlider("device-calibration-slider", deviceCalibration);
  // The copy button and the two icons it swaps between while Shift is held.
  const copyIcons = {".as-copy": {hidden: false},
                     ".as-download": {hidden: true}};
  const deviceCopy = Object.assign(makeElement(), {
    querySelector(selector) { return copyIcons[selector]; },
  });
  const deviceWarmSlider = deviceSlider("device-warm-slider", deviceWarm);
  const deviceTintSlider = deviceSlider("device-tint-slider", deviceTint);
  // The three channel transfer functions of the frame's tint filter. Only
  // their attributes matter: the page reads nothing back off them.
  const tintFuncs = Object.fromEntries(["r", "g", "b"].map(channel =>
    [`frame-tint-${channel}`, {
      attrs: {},
      setAttribute(key, value) { this.attrs[key] = value; },
    }]));
  // The per-knob reset arrow each numeric row carries. Scale is the one
  // without: a dropdown showing every value it has needs no way back.
  const deviceResets = Object.fromEntries(
    [devicePaper, deviceInk, deviceWarm, deviceTint,
     deviceCalibration].map(field => [
      field.id,
      {hidden: true, title: "", on: {}, dataset: {deviceReset: field.id},
       addEventListener(kind, fn) { this.on[kind] = fn; },
       press() { this.on.click(); }},
    ]));
  const deviceStepList = [devicePaper, deviceInk, deviceCalibration,
                          deviceWarm, deviceTint]
    .flatMap(field => [-1, 1].map(direction => ({
      dataset: {for: field.id, dir: String(direction)},
      on: {},
      addEventListener(kind, fn) { this.on[kind] = fn; },
      press(shiftKey = false) { this.on.pointerdown({shiftKey}); },
    })));
  const deviceSurface = makeElement();
  //: The sheet gesture: press and hold on the device surface shows the page
  //: untuned.
  const sheet = {
    press(button = 0) {
      deviceSurface.on.pointerdown({button, preventDefault() {}});
    },
    release(how = "pointerup") { deviceSurface.on[how](); },
  };
  const deviceCanvas = makeElement();
  deviceCanvas.getBoundingClientRect = () => ({left: 0, top: 0});
  deviceCanvas.getContext = () => ({
    drawImage(source) { deviceCanvas.painted = source; },
    getImageData: () => ({
      data: new Uint8ClampedArray([0, 0, 0, 255, 96, 96, 96, 255,
                                  200, 200, 200, 255, 255, 255, 255, 255]),
    }),
    putImageData(pixels) { deviceCanvas.pixels = [...pixels.data]; },
  });
  const deviceFrameImage = makeElement();
  const deviceReset = button("reset-device");
  // Everything carrying data-device-setting in the markup, which is what the
  // panel's own reset sweeps. A control missing from here is one the reset
  // silently skips in this harness while working on the page.
  const deviceSettings = [
    deviceModel, deviceColor, deviceFrame, deviceScale,
    devicePaper, deviceInk, deviceCalibration, deviceWarm, deviceTint,
  ];
  const stubs = {
    save: saveButton,
    saved: { textContent: "" },
    export: exportForm,
    presets: presetList,
    // Every value the note took, so the counting can be asserted and not
    // just the last line of it.
    built: recording(),
    // The export panel's foot, which is the row the build's bar is drawn in.
    buildbar: progressRow(),
    "tab-tune": pressStub("tune"),
    "tab-export": pressStub("export"),
    // The headings that fold the section or card under them.
    "page-toggle": Object.assign(pressStub("page"), {dataset: {fold: "page"}}),
    "mod-toggle": Object.assign(pressStub("mod"), {dataset: {fold: "mod"}}),
    "text-toggle": Object.assign(pressStub("text"), {dataset: {fold: "text"}}),
    "mod-dot": { hidden: true },
    // What a build leaves on the tab it ran behind.
    "tab-busy": { hidden: true },
    // What each tab says about work in the panel behind it that the .conf has
    // not got. Save is only under the knobs, so the export panel has no lit
    // button of its own to say it.
    "tune-unsaved": { hidden: true },
    "export-unsaved": { hidden: true },
    "source-note": { textContent: "" },
    // The row of sizes past the four boxes, which most families do not have.
    "more-row": { hidden: false },
    "mod-more-row": { hidden: false },
    "mod-name": { textContent: "" },
    // What a fractional size will be called on the card, one note per family.
    // Real elements: the note marks itself as a warning for a collision, so
    // its classes are read as well as its text.
    "ships-as": makeElement(),
    "mod-ships-as": makeElement(),
    // The variable-font block, and the row per axis it builds inside it.
    variable: { hidden: false },
    "axis-text-row": { hidden: false },
    "axis-bold-row": { hidden: false },
    "axis-rows": {
      children: [],
      replaceChildren(...kids) { this.children = kids; },
    },
    build: buildButton("one", "Build"),
    "build-all": buildButton("all", "Build all"),
    // The offer itself, which is the button rather than a row around it.
    // Assigned onto rather than spread: the disabled accessor is what records
    // the sequence, and a spread would copy its value and drop it.
    fetch: Object.assign(buildButton("fetch"), { hidden: false }),
    fetched: recording(),
    "have-fallbacks": { textContent: "" },
    // What this install is: the island under the specimen. The version, the
    // state of the asking, and the one button that state offers.
    about: { title: "" },
    // The version, and the name beside it that links the project. The link's
    // href comes from the server rather than the markup, so it is asserted.
    "about-number": { textContent: "" },
    "about-home": { href: "" },
    "about-state": recording(),
    "about-detail": { textContent: "" },
    // Both carry `hidden`: one of them is on offer at a time, and which one is
    // the whole of what the row says about updating.
    "check-now": Object.assign(buildButton("check", "Check now"),
                               { hidden: false }),
    "update-now": Object.assign(buildButton("update", "Update"),
                                { hidden: true }),
    "update-progress": progressRow(),
    updated: recording(),
    "device-toggle": Object.assign(pressStub("device"),
                                    {dataset: {fold: "device"}}),
    "device-surface": deviceSurface,
    "device-page": deviceCanvas,
    "device-frame": deviceFrameImage,
    "device-model": deviceModel,
    "device-color": deviceColor,
    "device-frame-shown": deviceFrame,
    "device-scale": deviceScale,
    "device-paper": devicePaper,
    "device-paper-slider": devicePaperSlider,
    "device-ink": deviceInk,
    "device-ink-slider": deviceInkSlider,
    "device-calibration": {hidden: true},
    "device-calibration-range": deviceCalibration,
    "device-calibration-slider": deviceCalibrationSlider,
    "device-copy": deviceCopy,
    "device-warm": deviceWarm,
    "device-warm-slider": deviceWarmSlider,
    "device-tint": deviceTint,
    "device-tint-slider": deviceTintSlider,
    ...tintFuncs,
    "device-ruler": makeElement(),
    "reset-device": deviceReset,
    knobs: form,
    // The notice drawn over the sheet when a render fails, and the button on it.
    "page-error": {
      hidden: true,
      parts: { what: { textContent: "" }, why: { textContent: "" } },
      querySelector(selector) { return this.parts[selector.slice(1)]; },
    },
    retry: button("retry"),
    status: { textContent: "" },
    undrawn: { textContent: "", hidden: true },
    uncovered: { textContent: "", hidden: true },
    "lh-auto": { checked: true, defaultChecked: true, addEventListener() {} },
    faces: { textContent: "" },
    // One badge per style, rebuilt whenever the choice changes.
    styles: { children: [], replaceChildren(...kids) { this.children = kids; } },
    family,
    sample,
    "reset-font": button("font"),
    "reset-page": button("page"),
    compare: {
      attrs: { "aria-pressed": "false" },
      getAttribute(k) { return this.attrs[k]; },
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(kind, fn) { if (kind === "click") this.fire = fn; },
    },
  };
  const fetches = { render: 0, checks: 0, applies: 0, defaults: 0,
                    updateReads: 0, bodies: [], saves: [], builds: [],
                    fallbacks: [], bodyReads: [], bitmaps: [] };
  let lastTimer = 0;
  const cancelled = new Set();
  const prompts = [];
  let answer = true;
  const keys = [], keyups = [], returns = [], resizes = [];
  let reloads = 0;
  const posted = (options) => {
    try { fetches.bodies.push(JSON.parse(options.body)); } catch { /* none */ }
  };
  const root = makeElement();
  root.dataset.appearance = "system";
  root.twoColumnClientWidth = Number(opts.viewportWidth) || 0;
  root.oneColumnClientWidth =
    Number(opts.oneColumnViewportWidth) || root.twoColumnClientWidth;
  root.twoColumnWidth =
    Number(opts.twoColumnWidth) || root.twoColumnClientWidth;
  Object.defineProperty(root, "clientWidth", {get() {
    return root.dataset.previewColumns === "one"
      ? root.oneColumnClientWidth : root.twoColumnClientWidth;
  }});
  Object.defineProperty(root, "scrollWidth", {get() {
    return root.dataset.previewColumns === "two"
      ? root.twoColumnWidth : root.clientWidth;
  }});
  const sandbox = {
    ...HOST,
    addEventListener(kind, fn) {
      if (kind === "resize") resizes.push(fn);
    },
    document: {
      getElementById: id => stubs[id],
      createElement: makeElement,
      createTextNode: (text) => ({ textContent: text }),
      // The folds and device reset are the two document-wide queries.
      querySelectorAll: (selector) => {
        if (selector === "[data-fold]") {
          return [stubs["page-toggle"], stubs["mod-toggle"],
                  stubs["device-toggle"], stubs["text-toggle"]];
        }
        if (selector === "[data-device-setting]") return deviceSettings;
        const deviceFor = selector.match(/^\[data-for="([^"]+)"\]$/)?.[1];
        if (deviceFor) {
          return deviceStepList.filter(button => button.dataset.for === deviceFor);
        }
        // Both spellings the page uses: one row's arrow while it is being
        // wired, and every arrow at once when their visibility is refreshed.
        if (selector === "[data-device-reset]") {
          return Object.values(deviceResets);
        }
        const resets = selector.match(/^\[data-device-reset="([^"]+)"\]$/)?.[1];
        return resets ? [deviceResets[resets]].filter(Boolean) : [];
      },
      addEventListener(kind, fn) {
        if (kind === "keydown") keys.push(fn);
        if (kind === "keyup") keyups.push(fn);
        if (kind === "visibilitychange") returns.push(fn);
      },
      //: Whether the tab is in the background. The page asks before it
      //: re-reads the folder, so a hidden one has to be able to say yes.
      hidden: false,
      documentElement: root,
      title: "",
    },
    // Coming back to the page is two different events -- a tab switch is the
    // document's, and clicking back from another window is this one's -- and
    // the page listens for both because neither covers the other.
    window: {
      addEventListener(kind, fn) { if (kind === "focus") returns.push(fn); },
    },
    location: { reload() { reloads++; } },
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    createElement: () => ({ dataset: {}, style: {}, textContent: "", title: "" }),
    // The family-switch guard. Answering yes by default keeps every older
    // block behaving as it did; the guard has a block of its own below.
    confirm: (message) => { prompts.push(message); return answer; },
    localStorage: storage,
    fetch: (url, options) => {
      if (String(url).includes("/render")) {
        fetches.render++;
        posted(options);
        const deferred = opts.deferredRenderBodies?.[fetches.render - 1];
        if (deferred) {
          let resolve, reject;
          const reading = new Promise((yes, no) => {
            resolve = yes;
            reject = no;
          });
          fetches.bodyReads.push({resolve, reject});
          if (!deferred.ignoreAbort) {
            options.signal.addEventListener("abort", () => {
              const error = new Error("The operation was aborted");
              error.name = "AbortError";
              reject(error);
            });
          }
          const response = {
            ok: deferred.ok, status: deferred.status ?? (deferred.ok ? 200 : 503),
            headers: {get: () => "0"},
          };
          response[deferred.ok ? "blob" : "text"] = () => reading;
          return Promise.resolve(response);
        }
        // A server that is not there at all: fetch rejects rather than
        // answering, which is what a stopped process looks like from here.
        if (opts.renderThrows) {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        if (opts.renderFails) {
          return Promise.resolve({
            ok: false, status: opts.renderFails.status,
            text: () => Promise.resolve(opts.renderFails.body),
          });
        }
        if (opts.renderOk) {
          return Promise.resolve({
            ok: true, status: 200, blob: () => Promise.resolve({fresh: true}),
            // How many characters the page could not draw, and how many of
            // those the coverage would not have built. A real answer always
            // carries all three; `undrawn`, `uncovered` and `coverageFix` in
            // the options are how a test asks for a page with holes in it.
            headers: {
              get: (name) => (
                name === "x-undrawn" ? String(opts.undrawn ?? 0)
                : name === "x-uncovered" ? String(opts.uncovered ?? 0)
                : name === "x-coverage-fix" ? (opts.coverageFix ?? "")
                : null),
            },
          });
        }
        // Never resolves: the page draws the blob it gets back, and there is
        // no image here to draw it into.
        return new Promise(() => {});
      }
      if (String(url).includes("/build")) {
        fetches.builds.push(JSON.parse(options.body));
        // A build the server refuses outright: nothing streams, and the panel
        // has to come back from it.
        if (opts.buildFails) {
          return Promise.resolve({
            ok: false, text: () => Promise.resolve("no such family") });
        }
        // A stream of progress lines, as the real one answers -- and split
        // across chunks mid-line, because that is the case the reader has to
        // get right and the one no tidy fixture would produce.
        const steps = opts.buildSteps ?? [
          { event: "plan", total: 2, out: "D:\\fonts\\cpfonts",
            families: ["Alto"] },
          { event: "size", family: "Alto", size: 12, done: 1, total: 2,
            bytes: 1200000 },
          { event: "size", family: "Alto", size: 13, done: 2, total: 2,
            bytes: 1211008 },
          // What the run wrote. A build lands on a card with a fixed amount of
          // room, so what it cost belongs beside what it did.
          { event: "done", out: "D:\\fonts\\cpfonts", bytes: 2411008,
            families: [
            { name: "Alto", bytes: 2411008, sizes: [12, 13], built: [12, 13],
              skipped: [], failed: [], removed: [], error: null }] },
        ];
        const text = steps.map(step => JSON.stringify(step)).join("\n") + "\n";
        const chunks = [text.slice(0, 40), text.slice(40)];
        let at = 0;
        return Promise.resolve({ ok: true, body: { getReader: () => ({
          read: () => Promise.resolve(at < chunks.length
            ? { value: chunks[at++], done: false }
            : { value: undefined, done: true }),
        }) } });
      }
      // The fallback fetch answers a line at a time as well, and in bytes: one
      // face is four fifths of the set, so the bar counts what has arrived
      // rather than how many files have.
      if (String(url).includes("/fallbacks")) {
        fetches.fallbacks.push(JSON.parse(options.body));
        const steps = opts.fetchSteps ?? [
          { event: "plan", files: 2, bytes: 20000000 },
          { event: "start", name: "NotoSans-Regular.ttf", got: 0,
            bytes: 20000000 },
          { event: "step", name: "NotoSans-Regular.ttf", got: 500000,
            bytes: 20000000 },
          { event: "start", name: "NotoSansCJKjp-Regular.otf", got: 500000,
            bytes: 20000000 },
          { event: "step", name: "NotoSansCJKjp-Regular.otf", got: 20000000,
            bytes: 20000000 },
          { event: "done", where: "D:\\fonts\\fallbacks", faces: 13 },
        ];
        const body = steps.map(step => JSON.stringify(step)).join("\n") + "\n";
        let sent = false;
        return Promise.resolve({ ok: true, body: { getReader: () => ({
          read: () => Promise.resolve(sent
            ? { value: undefined, done: true }
            : ((sent = true), { value: body, done: false })),
        }) } });
      }
      if (String(url).includes("/out")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(
          { out: "D:\\elsewhere" }) });
      }
      if (String(url).includes("/save")) {
        const sent = JSON.parse(options.body);
        fetches.saves.push(sent);
        // A config the server will not write -- a size that does not parse, a
        // name another family has taken, a read-only folder. Build leans on
        // this answer, so it has to exist. In the envelope FastAPI puts a
        // refusal in, because what the page has to show is the sentence.
        if (opts.saveFails) {
          return Promise.resolve({
            ok: false, text: () => Promise.resolve(
              JSON.stringify({ detail: "could not write arial.conf" })) });
        }
        // The real answer is the config read back, which after a save says
        // what was sent. Echoing a fixed fixture would leave the panel
        // looking dirty the moment a knob was not the one it named.
        //
        // The name is the one case where the file does not say what was sent:
        // it reaches a filename, so the server strips it to what one can hold
        // and an empty box means the name the files already have. Stripped
        // here too, or the page would never be told the difference.
        const typed = (sent.export && sent.export.name) || "";
        return Promise.resolve({ ok: true, json: () => Promise.resolve(
          { ...SAVED,
            name: typed.replace(/[^A-Za-z0-9_-]+/g, "") || sent.family,
            tuning: { line_height: null, ...sent.tuning } }) });
      }
      if (String(url).includes("/update/check")) {
        fetches.checks++;
        if (opts.checkThrows) return Promise.reject(new TypeError("no route"));
        return Promise.resolve({ json: () => Promise.resolve(
          { ...ABOUT, ...(opts.checked ?? {}) }) });
      }
      // Applying, which is the same path as a build: a line of JSON per step
      // and a bar that follows it. Only a POST, since the GET below is the
      // page reading what is already known.
      if (String(url).includes("/update") && options
          && options.method === "POST") {
        fetches.applies++;
        if (opts.applyFails) {
          return Promise.reject(new TypeError("connection lost"));
        }
        const steps = opts.updateSteps ?? [
          { event: "plan", version: "2.0.0", bytes: 1600000,
            notes_url: "https://example.invalid/", converting: false },
          { event: "step", got: 800000, bytes: 1600000 },
          { event: "step", got: 1600000, bytes: 1600000 },
          { event: "done", version: "2.0.0", kept: [], staged: [], converting: false,
            where: "versions/2.0.0" },
        ];
        const body = steps.map(step => JSON.stringify(step)).join("\n") + "\n";
        let sent = false;
        return Promise.resolve({ ok: true, body: { getReader: () => ({
          read: () => Promise.resolve(sent
            ? { value: undefined, done: true }
            : ((sent = true), { value: body, done: false })),
        }) } });
      }
      if (String(url).includes("/update")) {
        fetches.updateReads++;
        const answers = opts.restartAnswers;
        if (answers && fetches.updateReads > 1) {
          const answer = answers[Math.min(
            fetches.updateReads - 2, answers.length - 1)];
          if (answer instanceof Error) return Promise.reject(answer);
          return Promise.resolve({
            ok: true, json: () => Promise.resolve(answer) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(
          { ...ABOUT, ...(opts.about ?? {}) }) });
      }
      // The folder as it is now. `later` is what a second ask gets, which is
      // how a font arriving or a config being edited is put to the page.
      fetches.defaults++;
      const answer = fetches.defaults > 1 && opts.later ? opts.later : defaults;
      return Promise.resolve({ json: () => Promise.resolve(answer) });
    },
    // The chunks above are already text, so this only has to exist.
    TextDecoder: class { decode(chunk) { return chunk || ""; } },
    Option: class {
      constructor(text, value) {
        this.textContent = text; this.value = value; this.dataset = {};
      }
    },
    performance: { now: () => 0 },
    // The decoded page. Identity is what the assertions need: which body it
    // came from, and whether anything closed it.
    createImageBitmap: (blob) => {
      const bitmap = {width: 480, height: 800, source: blob, closed: false,
                      close() { this.closed = true; }};
      fetches.bitmaps.push(bitmap);
      return Promise.resolve(bitmap);
    },
    AbortController: class {
      constructor() {
        const listeners = [];
        this.signal = {
          aborted: false,
          addEventListener(kind, listener) {
            if (kind === "abort") listeners.push(listener);
          },
        };
        this.listeners = listeners;
      }
      abort() {
        if (this.signal.aborted) return;
        this.signal.aborted = true;
        for (const listener of this.listeners) listener();
      }
    },
    // A real enough timer: deferred to the next tick, and genuinely
    // cancellable. Running the callback on the spot would hide the one thing
    // worth asserting about a slider -- that a burst of events coalesces into
    // one page rather than one page per event.
    setTimeout: (fn) => {
      const id = ++lastTimer;
      setImmediate(() => { if (!cancelled.has(id)) fn(); });
      return id;
    },
    clearTimeout: (id) => { cancelled.add(id); },
    // Held steppers repeat on an interval; the stub must not start a real
    // one or the probe would never exit.
    setInterval: () => 0,
    clearInterval() {},
    // What the page reads on a first visit to guess which language somebody
    // wants a specimen and hyphenation patterns in. In preference order, as a
    // browser reports them.
    navigator: { languages: opts.languages ?? ["en-GB", "en"] },
    console,
  };
  return { form, listeners, sandbox, byName, clicks, sliderList, fetches,
           reloads: () => reloads,
           //: Come back to the page, as either event does.
           returning: () => { for (const fn of returns) fn(); },
           resize(clientWidth, twoColumnWidth,
                  oneColumnClientWidth = clientWidth) {
             root.twoColumnClientWidth = clientWidth;
             root.oneColumnClientWidth = oneColumnClientWidth;
             root.twoColumnWidth = twoColumnWidth;
             for (const fn of resizes) fn();
           },
           revertList, markList, compare: stubs.compare, keys, stepList, family, sample,
           faces: stubs.faces, badges: stubs.styles, exportForm, presetList,
           builds: buildButtons, built: stubs.built,
           builtSteps: stubs.built.steps,
           root: sandbox.document.documentElement,
           tabs: { tune: stubs["tab-tune"], export: stubs["tab-export"],
                   busy: stubs["tab-busy"],
                   tuneUnsaved: stubs["tune-unsaved"],
                   exportUnsaved: stubs["export-unsaved"],
                   press },
           fold: { page: stubs["page-toggle"], mod: stubs["mod-toggle"],
                   device: stubs["device-toggle"], text: stubs["text-toggle"],
                   dot: stubs["mod-dot"], press },
           progress: stubs.buildbar, bar: stubs.buildbar.bar,
           barFill: stubs.buildbar.fill,
           progressWhat: stubs.buildbar.what,
           progressCount: stubs.buildbar.count,
           buildEls: [stubs.build, stubs["build-all"]],
           fetchButton: stubs.fetch, fetchNote: stubs.fetched,
           save: saveButton, note: stubs.saved, prompts, keyups,
           pageError: stubs["page-error"], status: stubs.status,
           sheet,
           device: {
             model: deviceModel, color: deviceColor, frame: deviceFrame,
             scale: deviceScale, paper: devicePaper, ink: deviceInk,
             calibration: deviceCalibration, surface: deviceSurface,
             canvas: deviceCanvas, frameImage: deviceFrameImage,
             paperSlider: devicePaperSlider, inkSlider: deviceInkSlider,
             calibrationSlider: deviceCalibrationSlider,
             warm: deviceWarm, tint: deviceTint,
             warmSlider: deviceWarmSlider, tintSlider: deviceTintSlider,
             tintFuncs,
             copy: deviceCopy, copyIcons, resets: deviceResets,
             calibrationBox: stubs["device-calibration"],
             ruler: stubs["device-ruler"],
             edit(control) { control.on.input(); },
             change(control) { control.on.change(); },
             step(control, direction, shiftKey = false) {
               deviceStepList.find(button =>
                 button.dataset.for === control.id &&
                 Number(button.dataset.dir) === direction).press(shiftKey);
             },
             reset() { clicks["reset-device"](); },
           },
           about: { island: stubs.about, number: stubs["about-number"],
                    home: stubs["about-home"],
                    state: stubs["about-state"],
                    detail: stubs["about-detail"],
                    button: stubs["check-now"],
                    press: () => buildButtons.check(),
                    update: stubs["update-now"],
                    apply: () => buildButtons.update(),
                    updated: stubs.updated,
                    progress: stubs["update-progress"],
                    fill: stubs["update-progress"].fill },
           refuse() { answer = false; } };
}

async function run(storage, defaults, opts) {
  const env = makeEnv(storage, defaults, opts);
  env.modules = await evaluatePage(env.sandbox);
  return env;
}

// The picker is filled from /defaults, so anything about it has to wait for
// that promise. One macrotask flushes every microtask behind it.
const settle = () => new Promise(resolve => setImmediate(resolve));

async function loaded(storage, defaults, opts) {
  const env = await run(storage, defaults, opts);
  await settle();
  return env;
}

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: k => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: k => { delete data[k]; },
  };
}

let failures = 0;
function check(label, cond, detail = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${cond ? "" : "  " + detail}`);
  if (!cond) failures++;
}

// 0. Before any behaviour: the page loads at all. A module that reads a name
//    another module owns without importing it works here and throws there.
for (const { name, text } of sources) {
  const own = bound(text);
  const missing = [...borrowed(text)].filter(
    word => exported.has(word) && exported.get(word) !== name && !own.has(word));
  check(`${name} imports every name it borrows`, missing.length === 0,
        missing.map(word => `${word} (from ${exported.get(word)})`).join(", "));
}

// 0b. And nothing reaches for an imported name while the modules are still
//     coming up. The import graph has cycles, so a module body runs while a
//     module it imports may still be evaluating, and a binding read there is
//     in its dead zone -- a crash on load that no behaviour test can reach,
//     because the page never gets far enough to have behaviour. Wiring that
//     crosses modules belongs in start.js; a handle a module owns itself
//     cannot be in a dead zone and stays where it is.
for (const { name, text } of sources) {
  if (name === "app.js" || name === "start.js") continue;
  const taken = new Set();
  for (const [, names] of text.matchAll(/import\s*\{([^}]*)\}\s*from/g)) {
    for (const piece of names.split(",")) {
      if (piece.trim()) taken.add(piece.trim());
    }
  }
  // Statements at column zero that are not a declaration are work done on
  // import. Only those, since anything indented is inside something that runs
  // later, by which time every module is up.
  const reaching = [];
  let depth = 0;
  for (const line of text.split("\n")) {
    const bare = line.replace(/\/\/.*/, "").trim();
    if (depth === 0 && bare
        && !/^(export|import|const|let|function|class|async|\*|\/\*)/.test(bare)) {
      for (const word of taken) {
        if (new RegExp(`\\b${word}\\b`).test(bare)) reaching.push(`${word}: ${bare}`);
      }
    }
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
  }
  check(`${name} touches no imported name while loading`, reaching.length === 0,
        reaching.join(" | "));
}

// 1. Changing a remembered setting writes it to the right store.
{
  const store = fakeStorage();
  const env = await run(store);
  env.byName.margin.value = "22";
  env.byName.hyphenation.checked = true;
  env.listeners.input({ target: env.byName.margin });
  env.byName.size.value = "18";
  env.listeners.input({ target: env.byName.size });
  const saved = JSON.parse(store.data["crossglyph.page"]);
  check("a page knob is remembered",
        saved.margin === "22" && saved.hyphenation === true, JSON.stringify(saved));
  check("font knobs are not remembered", !("gamma" in saved) && !("size" in saved),
        JSON.stringify(saved));
  check("view size is remembered separately",
        store.data["crossglyph.size"] === "18", JSON.stringify(store.data));
  // The device select sits in the page group but belongs to the device store.
  // Saved here as well, it is applied back over loadDevice a moment after the
  // page settles, and the reader's chosen device reverts on its own. It slipped
  // through once because `data-device-setting` has no value, so asking whether
  // the dataset entry was truthy answered no for a control that carries it.
  check("the device select is not remembered as a page knob",
        !("device" in saved), JSON.stringify(saved));
}

// 2. A fresh load restores them.
{
  const store = fakeStorage({
    "crossglyph.page": JSON.stringify(
      { margin: "22", alignment: "left", language: "en", hyphenation: true, antialiased: false }),
    "crossglyph.size": "18.25",
  });
  const env = await run(store);
  check("margin restored", env.byName.margin.value === "22", env.byName.margin.value);
  check("select restored", env.byName.alignment.value === "left", env.byName.alignment.value);
  check("checkbox on restored", env.byName.hyphenation.checked === true);
  check("checkbox off restored", env.byName.antialiased.checked === false);
  check("view size restored", env.byName.size.value === "18.25", env.byName.size.value);

  const bad = await run(fakeStorage({"crossglyph.size": "99"}));
  check("an invalid stored size leaves the default standing",
        bad.byName.size.value === "13", bad.byName.size.value);

  // A page store written before the device select was excluded still carries a
  // device. Applying it puts that stale value over the reader's chosen one a
  // moment after the page settles, which is how a reader who picked X4 kept
  // finding X3 after every refresh. The device store owns this control.
  const stale = await run(fakeStorage({
    "crossglyph.page": JSON.stringify({margin: "22", device: "x3"}),
    "crossglyph.device": JSON.stringify({device: "x4"}),
  }));
  check("a stale device in the page store does not override the device store",
        stale.byName.device.value === "x4", stale.byName.device.value);
}

// 3. Resetting the page settings restores them and forgets them.
{
  const store = fakeStorage({
    "crossglyph.page": JSON.stringify({ margin: "22", hyphenation: true }),
    "crossglyph.size": "18",
  });
  const env = await run(store);
  check("the stored values were applied first",
        env.byName.margin.value === "22" && env.byName.size.value === "18");
  env.clicks.page();
  check("page reset restores the shipped defaults",
        env.byName.margin.value === "5" && env.byName.hyphenation.checked === false,
        `${env.byName.margin.value} ${env.byName.hyphenation.checked}`);
  check("page reset forgets the remembered settings",
        !("crossglyph.page" in store.data), JSON.stringify(store.data));
  check("page reset keeps the view size",
        env.byName.size.value === "18" && store.data["crossglyph.size"] === "18",
        JSON.stringify(store.data));
}

// 4. The whole point of splitting them: each reset leaves the other alone.
{
  const store = fakeStorage();
  const env = await run(store);
  env.byName.margin.value = "30";
  env.byName.hyphenation.checked = true;
  env.listeners.input({ target: env.byName.margin });
  env.byName.gamma.value = "2.5";
  env.byName.size.value = "18";
  env.listeners.input({ target: env.byName.size });

  env.clicks.font();
  check("font reset restores the font knobs",
        env.byName.gamma.value === "1", env.byName.gamma.value);
  check("font reset keeps the view size",
        env.byName.size.value === "18" && store.data["crossglyph.size"] === "18",
        JSON.stringify(store.data));
  check("font reset keeps the reader's page settings",
        env.byName.margin.value === "30" && env.byName.hyphenation.checked === true,
        `${env.byName.margin.value} ${env.byName.hyphenation.checked}`);
  check("font reset does not forget what was remembered",
        "crossglyph.page" in store.data, JSON.stringify(store.data));

  env.byName.gamma.value = "0.5";
  env.clicks.page();
  check("page reset leaves the font knobs alone",
        env.byName.gamma.value === "0.5", env.byName.gamma.value);
  check("page reset still leaves the view size alone",
        env.byName.size.value === "18" && store.data["crossglyph.size"] === "18",
        JSON.stringify(store.data));
}

// 5. The slider and the field are one value in two controls.
{
  const store = fakeStorage();
  const env = await run(store);
  const slider = env.sliderList.find(s => s.dataset.sliderFor === "gamma");

  slider.value = "2.5";
  slider.fire();
  check("moving the slider moves the field",
        env.byName.gamma.value === "2.5", env.byName.gamma.value);

  // gamma runs 0.3..4, so 2.5 sits (2.5 - 0.3) / 3.7 of the way along.
  check("the filled track follows the value",
        slider.style.props["--fill"] === "59%", slider.style.props["--fill"]);

  env.byName.gamma.value = "1";
  env.clicks.font();
  check("resetting the field moves the slider back",
        slider.value === "1", slider.value);
  check("resetting repaints the filled track",
        slider.style.props["--fill"] === "19%", slider.style.props["--fill"]);
}

// 6. Remembered values have to reach their sliders too, or a slider shows the
//    default while its field shows what was restored.
{
  const store = fakeStorage({
    "crossglyph.page": JSON.stringify({ margin: "31" }),
    "crossglyph.size": "18.25",
  });
  const env = await run(store);
  const margin = env.sliderList.find(s => s.dataset.sliderFor === "margin");
  const size = env.sliderList.find(s => s.dataset.sliderFor === "size");
  check("a restored page value reaches its slider",
        margin.value === "31", `${margin.value} vs field ${env.byName.margin.value}`);
  check("the restored view size reaches its slider",
        size.value === "18.25", `${size.value} vs field ${env.byName.size.value}`);
}

// 7. A stored option that no longer exists leaves the device default standing.
{
  const store = fakeStorage({
    "crossglyph.page": JSON.stringify({ alignment: "diagonal" }),
  });
  const env = await run(store);
  check("an unknown select value is ignored, not applied",
        env.byName.alignment.value === "justify", env.byName.alignment.value);
}

// 8. The arrow marks a knob that differs from a baseline it can offer, which
//    is what makes the column readable: what you have touched, and under that,
//    what this font changes from stock.
{
  const env = await run(fakeStorage());
  const arrow = name => env.revertList.find(r => r.dataset.reset === name);
  check("a knob its config leaves at stock is unmarked at rest",
        arrow("hinting").hidden === true, arrow("hinting").title);
  check("one its config moves is marked, offering stock",
        arrow("gamma").hidden === false && /stock value/.test(arrow("gamma").title),
        arrow("gamma").title);

  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });
  check("changing it marks it against the config instead",
        arrow("gamma").hidden === false &&
          /what the config has/.test(arrow("gamma").title), arrow("gamma").title);
  check("an untouched one is not marked", arrow("margin").hidden === true);
}

// 9. The arrow is a bypass toggle, not a one-way reset: click to see the
//    default, click again to get your value back, as often as you like.
{
  const store = fakeStorage();
  const env = await run(store);
  const arrow = name => env.revertList.find(r => r.dataset.reset === name);
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });

  arrow("gamma").click();
  check("one click shows what the config has",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);
  check("the arrow stays, marked as set aside",
        arrow("gamma").hidden === false && arrow("gamma").dataset.state === "on");

  arrow("gamma").click();
  check("clicking again puts your value back",
        env.byName.gamma.value === "2.5", env.byName.gamma.value);
  check("and it is no longer marked set aside",
        arrow("gamma").dataset.state === "off");

  env.byName.size.value = "18";
  env.listeners.input({ target: env.byName.size });
  arrow("size").click();
  check("a size comparison does not replace the remembered view",
        env.byName.size.value === "13" && store.data["crossglyph.size"] === "18",
        `${env.byName.size.value} ${store.data["crossglyph.size"]}`);
  arrow("size").click();
  check("returning from the comparison restores the remembered view",
        env.byName.size.value === "18" && store.data["crossglyph.size"] === "18",
        `${env.byName.size.value} ${store.data["crossglyph.size"]}`);

  arrow("gamma").click();
  env.byName.gamma.value = "3";
  env.listeners.input({ target: env.byName.gamma });
  arrow("gamma").click();
  check("editing a bypassed knob drops what was set aside",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);
}

// 10. Comparing the whole tuning at once, with size held.
{
  const env = await run(fakeStorage());
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });
  env.byName.size.value = "18";
  env.listeners.input({ target: env.byName.size });
  env.byName.margin.value = "30";
  env.listeners.input({ target: env.byName.margin });

  env.compare.fire();
  check("comparing sets the tuning aside",
        env.byName.gamma.value === "1", env.byName.gamma.value);
  check("but never the size -- it is which size you are working at, and 13 is "
        + "this page's default rather than the device's",
        env.byName.size.value === "18", env.byName.size.value);
  check("and never the reader's own page settings",
        env.byName.margin.value === "30", env.byName.margin.value);
  check("the button says it is on",
        env.compare.getAttribute("aria-pressed") === "true");

  env.compare.fire();
  check("and turning it off brings the tuning back",
        env.byName.gamma.value === "2.5", env.byName.gamma.value);
}

// 11. Backslash drives the same toggle, except while typing.
{
  const env = await run(fakeStorage());
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });

  // Every listener, as the document would: more than one module watches for a
  // key, and which of them registered first is not something to depend on.
  const press = (target) => {
    for (const listener of env.keys) {
      listener({ key: "\\", target, preventDefault() {} });
    }
  };

  press({ tagName: "BODY" });
  check("backslash compares", env.byName.gamma.value === "1", env.byName.gamma.value);

  press({ tagName: "TEXTAREA" });
  check("but not while typing, where it is a character",
        env.byName.gamma.value === "1", env.byName.gamma.value);
}

// 12. Stepping a knob that is set aside replaces what was set aside. Assigning
//     .value fires no input event, so the stepper path has to drop the stash
//     itself -- without it the arrow jumps back to the value from before the
//     comparison rather than the one you just dialled in.
{
  const env = await run(fakeStorage());
  const arrow = env.revertList.find(r => r.dataset.reset === "gamma");
  const plus = env.stepList.find(s => s.dataset.for === "gamma" && s.dataset.dir === "1");

  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });
  arrow.click();
  check("set aside, so the knob is at what the config has",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);

  plus.press();
  check("stepping moves it off that",
        env.byName.gamma.value === "1.25", env.byName.gamma.value);
  check("and it is no longer marked set aside", arrow.dataset.state === "off");

  arrow.click();
  check("so the arrow now compares against the config, not the old value",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);
  arrow.click();
  check("and puts back what was actually dialled in",
        env.byName.gamma.value === "1.25", env.byName.gamma.value);
}

// 12a. Shift is a coarse press, and it lands on the multiples of what the knob
//      declares as a big move rather than carrying the fraction along. These
//      values are read off the panel and written into a .conf, so where a press
//      lands matters as much as how far it went: from 13.25 the size knob is
//      wanted at 14 and 15, not at 15.75 and 18.25.
{
  const env = await run(fakeStorage());
  const press = (name, direction, shiftKey) => env.stepList.find(
    one => one.dataset.for === name &&
           Number(one.dataset.dir) === direction).press(shiftKey);

  env.byName.size.value = "13.25";
  env.listeners.input({ target: env.byName.size });
  press("size", 1, true);
  check("a coarse press lands on the whole point below the next one",
        env.byName.size.value === "14", env.byName.size.value);
  press("size", 1, true);
  check("and keeps to them from there",
        env.byName.size.value === "15", env.byName.size.value);
  press("size", -1, false);
  check("while a bare press is still the step the knob steps in",
        env.byName.size.value === "14.75", env.byName.size.value);
  press("size", -1, true);
  check("and a coarse press back rounds the other way",
        env.byName.size.value === "14", env.byName.size.value);
  check("the slider follows a coarse press like any other",
        env.sliderList.find(one => one.dataset.sliderFor === "size")
          .value === "14");

  // Each knob declares its own, in the unit it counts in: half a point of
  // gamma, five pixels of margin. Ten times the step would be neither.
  press("gamma", 1, true);
  check("gamma takes the half it declares",
        env.byName.gamma.value === "1.5", env.byName.gamma.value);
  press("margin", 1, true);
  check("and margin the five it declares",
        env.byName.margin.value === "10", env.byName.margin.value);
}

// 12b. The round number the derived coarse press is made of, asked directly:
//      one wdth axis exercises a single case of it, and what the rule has to
//      hold is that every answer is a number somebody would have picked.
{
  const env = await run(fakeStorage());
  const round = env.modules.get("knobs.js").roundStep;
  const answers = [1.5625, 50, 8.5, 0.625, 3.125, 1, 200].map(round).join();
  check("every derived press is a 1-2-5 number at or above what was asked",
        answers === "2,50,10,1,5,1,200", answers);
  check("and a range that says nothing has none to derive",
        round(0) === 0 && round(NaN) === 0);
}

// 13. Typing a value moves its slider. Only setField did that, so a typed
//     number left the slider parked until the field lost focus.
{
  const env = await run(fakeStorage());
  const slider = env.sliderList.find(s => s.dataset.sliderFor === "margin");
  env.byName.margin.value = "18";
  env.listeners.input({ target: env.byName.margin });
  check("a typed value moves its slider", slider.value === "18", slider.value);
}

// 14. Custom sample text survives a reload, and clearing it forgets it. Fired
//     on the box itself, not on the form: it sits under the specimen, joined to
//     the form by `form="knobs"`, and an event that bubbles up the DOM never
//     reaches a form the control is not inside.
{
  const store = fakeStorage();
  const env = await run(store);
  check("the text box is listened to directly, wherever the page puts it",
        typeof env.byName.text.on.input === "function");
  env.byName.text.value = "Пример текста 12345";
  env.byName.text.on.input({ target: env.byName.text });
  check("custom text is remembered",
        store.data["crossglyph.text"] === "Пример текста 12345",
        store.data["crossglyph.text"]);

  const back = await run(store);
  check("and comes back on the next load",
        back.byName.text.value === "Пример текста 12345", back.byName.text.value);

  back.byName.text.value = "";
  back.byName.text.on.input({ target: back.byName.text });
  check("emptying the box forgets it, so the shipped sample returns",
        !("crossglyph.text" in store.data), JSON.stringify(store.data));
}

// 15. An unnamed control still asks for a page. "Use the font's own" carries an
//    id and no name, so guarding the input handler on the name left it
//    re-enabling the field and never re-rendering -- you could switch it back
//    on and watch the page not change.
{
  const env = await loaded(fakeStorage());
  const before = env.fetches.render;
  env.listeners.input({ target: { dataset: {} } });
  // A page is asked for on the next tick, not on the spot: the request is
  // coalesced, so it lands once the burst it belongs to is over.
  await settle();
  check("an unnamed control still triggers a render",
        env.fetches.render === before + 1, `${before} -> ${env.fetches.render}`);
}

// 16. Blocked storage must not break the page.
{
  const hostile = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };
  let threw = null;
  try {
    const env = await run(hostile);
    env.listeners.input({ target: env.byName.margin });
    env.clicks.page();
    env.clicks.font();
  } catch (error) { threw = error; }
  check("a browser with storage blocked still works", threw === null, String(threw));
}

// 17. Corrupt JSON must not break the page.
{
  const store = fakeStorage({ "crossglyph.page": "{not json" });
  let threw = null;
  try { await run(store); } catch (error) { threw = error; }
  check("corrupt stored data is ignored", threw === null, String(threw));
}

// 18. The font picker: what the source folder holds, with the family the app
//     was started on selected.
{
  const env = await loaded(fakeStorage());
  check("the picker lists every family",
        env.family.options.map(o => o.value).join() === "Sample,Vari,Alto",
        env.family.options.map(o => o.value).join());
  check("and starts on the one the app was started on",
        env.family.value === "Alto", env.family.value);
  const shown = () => env.badges.children.map(b => b.dataset.loaded).join();
  check("a badge per style, lit for the ones this family has",
        shown() === "yes,yes,no,no", shown());

  env.family.choose("Sample");
  check("choosing another family renders it",
        env.fetches.bodies.at(-1).family === "Sample",
        JSON.stringify(env.fetches.bodies.at(-1)));
  check("and the badges follow the choice", shown() === "yes,yes,yes,no",
        shown());
}

// 19. The choice is remembered: it is what you are looking at, like the sample
//     text, so neither Reset button has an opinion about it.
{
  const store = fakeStorage();
  const env = await loaded(store);
  env.family.choose("Sample");
  check("the chosen family is remembered",
        store.data["crossglyph.family"] === "Sample",
        JSON.stringify(store.data));

  env.clicks.font();
  env.clicks.page();
  check("and neither reset throws it away", env.family.value === "Sample",
        env.family.value);

  const back = await loaded(store);
  check("it comes back on the next load", back.family.value === "Sample",
        back.family.value);
}

// 20. A remembered family whose files have left the folder must not be posted:
//     the server would refuse it and the page would open on an error.
{
  const store = fakeStorage({ "crossglyph.family": "Gone" });
  const env = await loaded(store);
  check("an unknown remembered family falls back to the startup one",
        env.family.value === "Alto", env.family.value);
}

// 21. Started on a bare --font, which is no family and cannot become one. It
//     has to stay selectable, or choosing another font would strand it.
{
  const bare = { ...DEFAULTS, family: null };
  const env = await loaded(fakeStorage(), bare);
  check("a file the app was started on is the first entry",
        env.family.options[0].textContent === "Alto-Medium.otf" &&
        env.family.options[0].value === "",
        JSON.stringify(env.family.options[0]));
  check("and is what is selected", env.family.value === "", env.family.value);
  check("with the families after it",
        env.family.options.length === 4, String(env.family.options.length));
}

// 21b. The family the tool ships is offered only while the workspace is empty.
//      The entry says so, or it reads as a font you put there and forgot --
//      and its disappearance, once you add one of your own, reads as a bug.
{
  const shipped = { ...DEFAULTS, family: "Literata", font: null, families: [
    { name: "Literata", faces: ["bold", "bold italic", "italic", "regular"],
      conf: "literata.conf", derived: true, bundled: true,
      tuning: { gamma: 1, weight: 0, hinting: "normal",
                thresholds: [4, 8, 12], line_height: null },
      export: { name: "Literata", sizes: "12 14 16 18", sizes_mod: "", mod_suffix: "Mod",
                intervals: "reading", ranges: "",
                fallbacks: true, fallback1: "", fallback2: "" } }] };
  const env = await loaded(fakeStorage(), shipped);
  check("the bundled family says so on its entry",
        env.family.options[0].textContent === "Literata (bundled)",
        env.family.options[0].textContent);
  check("and is still addressed by its own name",
        env.family.value === "Literata", env.family.value);
}

// 21c. A font of your own is named and nothing else.
{
  const env = await loaded(fakeStorage(), DEFAULTS);
  check("a font of your own carries no marker",
        [...env.family.options].every(o => !o.textContent.includes("bundled")),
        env.family.options.map(o => o.textContent).join(", "));
}

// 22. The knobs open at what the family's .conf says, not at the converter's
//     defaults -- that config is the build the card would get.
{
  const env = await loaded(fakeStorage());
  check("a knob opens at what the config says",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);
  // Marked, but against stock rather than against the config: nobody has
  // changed it, and what the arrow has left to offer is the value the
  // converter would use if this config did not exist.
  const gammaArrow = env.revertList.find(r => r.dataset.reset === "gamma");
  check("and is marked against stock, which is what it differs from",
        gammaArrow.hidden === false && /stock value/.test(gammaArrow.title),
        gammaArrow.title);
  check("so there is nothing to save yet", env.save.disabled === true);
  check("and the button names the file it would write",
        env.save.textContent === "Save to alto.conf", env.save.textContent);
}

// 23. The arrow compares against the config, and untuned against the factory
//     defaults. Two baselines, because they answer different questions.
{
  const env = await loaded(fakeStorage());
  const arrow = env.revertList.find(r => r.dataset.reset === "gamma");

  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });
  check("editing off the saved value marks the knob", arrow.hidden === false);
  check("and offers a save", env.save.disabled === false);

  arrow.click();
  check("the arrow bypasses to the saved value, not to 1",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);
  arrow.click();
  check("and back", env.byName.gamma.value === "2.5", env.byName.gamma.value);

  env.compare.fire();
  check("untuned strips to the converter default, config and all",
        env.byName.gamma.value === "1", env.byName.gamma.value);
  env.compare.fire();
  check("and puts the whole tuning back",
        env.byName.gamma.value === "2.5", env.byName.gamma.value);
}

// 23b. Untuned is a layer above each control's own arrow. Turning that whole
//      panel comparison off must not restore a value the arrow had set aside.
//      Numeric, select and compound controls share the path, so keep all three
//      representative shapes in the regression.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Sample");
  await settle();
  const auto = env.sandbox.document.getElementById("lh-auto");
  const cases = [
    {
      name: "gamma",
      edit() { env.byName.gamma.value = "1.05"; },
      stock() { return env.byName.gamma.value === "1"; },
      edited() { return env.byName.gamma.value === "1.05"; },
    },
    {
      name: "hinting",
      edit() { env.byName.hinting.value = "light"; },
      stock() { return env.byName.hinting.value === "normal"; },
      edited() { return env.byName.hinting.value === "light"; },
    },
    {
      name: "line_height",
      edit() {
        auto.checked = false;
        env.byName.line_height.value = "1.2";
      },
      stock() { return auto.checked === true; },
      edited() {
        return auto.checked === false && env.byName.line_height.value === "1.2";
      },
    },
  ];

  for (const one of cases) {
    one.edit();
    env.listeners.input({target: env.byName[one.name]});
    const arrow = env.revertList.find(r => r.dataset.reset === one.name);
    arrow.click();
    check(`${one.name} is set aside at stock`,
          one.stock() && arrow.dataset.state === "on");
  }

  env.compare.fire();
  env.compare.fire();
  for (const one of cases) {
    const arrow = env.revertList.find(r => r.dataset.reset === one.name);
    check(`Untuned leaves ${one.name} set aside`,
          one.stock() && arrow.dataset.state === "on");
    arrow.click();
    check(`${one.name} still restores its own value`, one.edited());
  }
}

// 24. Saving posts the panel, and takes its new baseline from the answer.
{
  const env = await loaded(fakeStorage());
  env.byName.gamma.value = "2";
  env.listeners.input({ target: env.byName.gamma });

  await env.save.click();
  const posted = env.fetches.saves.at(-1);
  check("the save names the family", posted.family === "Alto",
        JSON.stringify(posted));
  check("and carries the whole panel", posted.tuning.gamma === 2 &&
        "weight" in posted.tuning, JSON.stringify(posted.tuning));
  check("what came back becomes the baseline, so nothing is left to save",
        env.save.disabled === true);
  check("and the note says what moved where",
        env.note.textContent === "gamma \u2192 alto.conf", env.note.textContent);

  // Saving is what makes every knob agree with the config at once. The arrow
  // has to survive that: without somewhere else to point it would empty the
  // column exactly when the font became worth reading, and stock would be
  // reachable only by resetting the whole panel.
  const arrow = env.revertList.find(r => r.dataset.reset === "gamma");
  check("the arrow stays after a save, now offering stock",
        arrow.hidden === false && /stock value/.test(arrow.title), arrow.title);

  arrow.click();
  check("pressing it shows the stock value, not the value just saved",
        env.byName.gamma.value === "1", env.byName.gamma.value);
  check("and says so while it is held there",
        /Showing the stock value/.test(arrow.title), arrow.title);
  check("which is a change against the file, so it can be saved",
        env.save.disabled === false, String(env.save.disabled));

  arrow.click();
  check("pressing again brings the saved value back",
        env.byName.gamma.value === "2", env.byName.gamma.value);
  check("leaving nothing to save again", env.save.disabled === true);
}

// 25. Save writes the page, comparison or no comparison. The page is the only
//     thing saying what this font will look like, so a Save that wrote a value
//     set aside a minute ago -- one nothing on screen shows -- would be a save
//     nobody could check.
{
  const env = await loaded(fakeStorage());
  env.byName.gamma.value = "2";
  env.listeners.input({ target: env.byName.gamma });
  env.compare.fire();
  check("comparing shows the factory default",
        env.byName.gamma.value === "1", env.byName.gamma.value);

  await env.save.click();
  check("saving writes what is on screen",
        env.fetches.saves.at(-1).tuning.gamma === 1,
        JSON.stringify(env.fetches.saves.at(-1).tuning));
  check("the page keeps showing it", env.byName.gamma.value === "1",
        env.byName.gamma.value);
  check("and the comparison is over rather than still holding a value",
        env.compare.getAttribute("aria-pressed") === "false",
        env.compare.getAttribute("aria-pressed"));
}

// 25a. Peeking one knob is the same story one row down: while the arrow is on,
//      the panel is showing what the config says, so there is nothing to save
//      -- and pressing Save anyway writes the page rather than the value the
//      arrow is holding.
{
  const env = await loaded(fakeStorage());
  env.byName.gamma.value = "2";
  env.listeners.input({ target: env.byName.gamma });
  check("an edit offers a save", env.save.disabled === false);

  const arrow = env.revertList.find(one => one.dataset.reset === "gamma");
  arrow.click();
  check("peeking shows what the config has", env.byName.gamma.value === "1.2",
        env.byName.gamma.value);
  check("and there is nothing to save while it does",
        env.save.disabled === true);

  // Switching family asks the same question the button does, and gets the same
  // answer: the panel says what the config says, so there is nothing here to
  // defend. The value the arrow is holding is one press from being back and
  // was never going to survive a reload either, so counting it would leave a
  // dark Save button and a warning about unsaved changes contradicting each
  // other over one knob.
  env.family.choose("Sample");
  check("and switching family does not ask either",
        env.prompts.length === 0, JSON.stringify(env.prompts));
  check("the family switched", env.family.value === "Sample",
        env.family.value);
}

// 26. Switching family loads that family's own settings.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Sample");
  check("the knobs follow the picker", env.byName.gamma.value === "1",
        env.byName.gamma.value);
  check("and the Save button follows it too",
        env.save.textContent === "Save to sample.conf", env.save.textContent);
}

// 27. Unsaved knobs are the only thing on the page with nowhere else to live,
//     so switching away asks first.
{
  const env = await loaded(fakeStorage());
  env.refuse();
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });

  env.family.choose("Sample");
  check("switching with unsaved knobs asks", env.prompts.length === 1,
        JSON.stringify(env.prompts));
  check("and refusing stays where it was", env.family.value === "Alto",
        env.family.value);
  check("with the edit intact", env.byName.gamma.value === "2.5",
        env.byName.gamma.value);
}

// 28. The export panel is the same config seen from the other end: it opens
//     at what the family builds as, and follows the picker.
{
  const env = await loaded(fakeStorage());
  // A box per step, so a config with two sizes leaves the other two empty
  // rather than showing "12 13" in a field and calling it four steps.
  const boxes = () => ["size1", "size2", "size3", "size4", "size_more"]
    .map(name => env.exportForm.elements[name].value).join("|");
  check("sizes open at what the config says, a step to a box",
        boxes() === "12|13|||", boxes());
  // What the reader chose, which is what the config spells. Boxes another
  // tick already carries are shown on as well, and those are block 71's.
  const chosen = () => env.presetList.querySelectorAll()
    .filter(box => box.dataset.chosen === "yes").map(box => box.value).join();
  check("coverage opens ticked as the config spells it",
        chosen() === "reading,cyrillic", chosen());
  check("and a fallback family is shown as a family",
        env.exportForm.elements.fallback1.value === "Sample",
        env.exportForm.elements.fallback1.value);

  env.family.choose("Sample");
  check("the export half follows the picker too",
        boxes() === "12|14|16|18|", boxes());
  // The guard runs after the picker has moved, so an export comparison against
  // its value asks whether this panel matches the family being switched *to* --
  // which it never does. Every switch then claimed unsaved changes.
  check("and a switch nobody edited asks nothing",
        env.prompts.length === 0, JSON.stringify(env.prompts));
  check("including the fallback pickers, which drop the family being built",
        env.exportForm.elements.fallback1.options
          .map(o => o.value).join() === ",Vari,Alto",
        env.exportForm.elements.fallback1.options.map(o => o.value).join());
}

// 29. Editing it offers a save, and the save carries it beside the tuning.
{
  const env = await loaded(fakeStorage());
  check("nothing to save at rest", env.save.disabled === true);

  env.exportForm.elements.size1.value = "10";
  env.exportForm.edit("size1");
  check("editing an export setting offers a save",
        env.save.disabled === false);

  await env.save.click();
  const posted = env.fetches.saves.at(-1);
  // The boxes go back to the one list the config keeps, in the order they sit
  // in -- Alto opens at 12 and 13, and only the first was touched.
  check("and the save carries both halves",
        posted.export.sizes === "10 13" && posted.tuning.gamma === 1.2,
        JSON.stringify(posted));
  check("with coverage as the config spells it",
        posted.export.intervals === "reading,cyrillic", posted.export.intervals);
  check("and the panel is clean again", env.save.disabled === true);
}

// 29a. Putting an export setting back is not a change. A flag set by the first
//      edit stays set through the undo, and then Save is lit with nothing to
//      save -- which is the one thing that button must never say.
{
  const env = await loaded(fakeStorage());
  const sizes = env.exportForm.elements;
  sizes.size1.value = "10";
  env.exportForm.edit("size1");
  check("an edit offers a save", env.save.disabled === false);

  sizes.size1.value = "12";
  env.exportForm.edit("size1");
  check("and putting it back takes the offer away", env.save.disabled === true);

  // Coverage is a set, and the config may spell the same ticks in either
  // order: unticking and reticking must not leave the panel dirty either.
  // Through the box itself, as a click does: a tick is a choice the panel
  // records, and the other boxes are worked out from it, so poking `checked`
  // is not a tick any more than moving a needle is a measurement.
  const box = env.presetList.querySelectorAll().find(one => one.value === "reading");
  const tick = (on) => { box.checked = on; env.exportForm.on.input({target: box}); };
  tick(false);
  check("unticking a preset is a change", env.save.disabled === false);
  tick(true);
  check("and ticking it back is not", env.save.disabled === true);
}

// 29b. The fallbacks are on the page as well as in the build, so every render
//      carries the ones the panel currently shows -- and changing them draws
//      the page again, which is the only way to see what they do.
{
  const env = await loaded(fakeStorage());
  const last = () => env.fetches.bodies.at(-1);
  check("a render carries the family's fallbacks as the panel shows them",
        last().fallback1 === "Sample" && last().fallbacks === false,
        JSON.stringify({ fallback1: last().fallback1,
                         fallbacks: last().fallbacks }));
  check("and the coverage, which decides which bundled faces those are",
        last().intervals === "reading,cyrillic", last().intervals);

  const before = env.fetches.render;
  env.exportForm.elements.fallbacks.checked = true;
  env.exportForm.edit("fallbacks");
  await settle();
  check("ticking the bundled faces redraws the page",
        env.fetches.render > before, `${before} -> ${env.fetches.render}`);
  check("with them on the request", last().fallbacks === true);

  // A size is a build setting and nothing else: redrawing for it would
  // rasterize the same font again on every keystroke.
  const after = env.fetches.render;
  env.exportForm.elements.size1.value = "11";
  env.exportForm.edit("size1");
  await settle();
  check("but a size does not", env.fetches.render === after);
}

// 30. Building, which is the whole point of the export half.
{
  const env = await loaded(fakeStorage());
  await env.builds.one();
  check("Build builds the family on screen",
        env.fetches.builds.at(-1).family === "Alto",
        JSON.stringify(env.fetches.builds.at(-1)));
  // Not where: the note has one reserved line in the panel's foot, and the
  // output box three rows above it is already showing the folder.
  check("and says what it did and what it cost",
        env.built.textContent === "2 built (2.4 MB), 0 already current",
        env.built.textContent);
  check("having counted its way there rather than sitting on 'building…'",
        env.progressCount.steps.includes("1 of 2") &&
        env.progressCount.steps.includes("2 of 2"),
        JSON.stringify(env.progressCount.steps));
  check("and named what it was building at each step",
        env.progressWhat.steps.includes("Alto 12") &&
        env.progressWhat.steps.includes("Alto 13"),
        JSON.stringify(env.progressWhat.steps));
  // Sizes run across a pool, so nothing lands until one of them finishes.
  // Counting from the plan put a determinate zero on screen for the whole of
  // that -- the sweep stopped, the bar sat at "0 of 2" looking stalled, and
  // then started filling, which is two starts and one of them a fake.
  check("never counting from a zero it had not been told",
        !env.progressCount.steps.includes("0 of 2"),
        JSON.stringify(env.progressCount.steps));
  check("with the scale said in words until the first one lands",
        env.progressWhat.steps.includes("building 2 sizes…"),
        JSON.stringify(env.progressWhat.steps));

  await env.builds.all();
  check("Build all builds every family",
        env.fetches.builds.at(-1).family === "",
        JSON.stringify(env.fetches.builds.at(-1)));
  check("and a panel that matches its config is not written on the way",
        env.fetches.saves.length === 0,
        JSON.stringify(env.fetches.saves));

  // Both buttons, not only the one pressed: the server builds one family at a
  // time, so the second press would queue a run behind the progress on screen.
  for (const button of env.buildEls) {
    check("a build takes both buttons out and gives them back",
          button.states.join() === "true,false,true,false", button.states.join());
  }
}

// 30a. A build that goes wrong still gives the buttons back -- otherwise the
//      panel is dead until a reload, and the failure it is reporting is the
//      moment you most want to press Build again.
{
  const env = await loaded(fakeStorage(), undefined, { buildFails: true });
  await env.builds.one();
  check("a failed build says so", env.built.textContent.includes("no such family"),
        env.built.textContent);
  check("and the buttons come back anyway",
        env.buildEls.every(b => b.disabled === false),
        env.buildEls.map(b => b.disabled).join());
}

// 30a1. Build writes the panel first. The .conf is the only channel a build
//      has, so a coverage tick that is only on the page is left out of the
//      staleness comparison entirely: every size looks current, and the build
//      says so -- which reads as "the setting did nothing" rather than "the
//      setting never arrived".
{
  const env = await loaded(fakeStorage());
  env.exportForm.elements.fallbacks.checked = true;
  env.exportForm.edit("fallbacks");
  await env.builds.one();
  check("Build writes the panel into the config first",
        env.fetches.saves.length === 1 &&
        env.fetches.saves[0].export.fallbacks === true,
        JSON.stringify(env.fetches.saves));
  check("and then builds, rather than one instead of the other",
        env.fetches.builds.length === 1 &&
        env.built.textContent.includes("2 built"),
        env.built.textContent);

  // The save is what made the panel clean, so the second press has nothing to
  // write -- a build should not rewrite a file it just agreed with.
  await env.builds.one();
  check("a second press writes nothing",
        env.fetches.saves.length === 1, JSON.stringify(env.fetches.saves));
}

// 30a2. A save the server refuses stops the build. Carrying on would build from
//      the file as it stands and hand back a font that is not the one on the
//      page, with a progress line saying it worked.
{
  const env = await loaded(fakeStorage(), undefined, { saveFails: true });
  env.exportForm.elements.fallbacks.checked = true;
  env.exportForm.edit("fallbacks");
  await env.builds.one();
  check("a refused save cancels the build",
        env.fetches.builds.length === 0, JSON.stringify(env.fetches.builds));
  check("and says the build did not happen",
        env.built.textContent.startsWith("not built"), env.built.textContent);
  check("with the server's own sentence under the button, not the envelope "
        + "it arrived in",
        env.note.textContent === "could not write arial.conf",
        env.note.textContent);
  // That button is under the knobs, and behind a tab this panel does not show
  // it. The refusal is the half worth having -- a name another family has
  // taken, a size the device could not read -- so it is said beside the press
  // that failed as well, where whoever pressed it is looking.
  check("and the reason beside the press that failed, not only under Save",
        env.built.textContent.includes("could not write arial.conf"),
        env.built.textContent);
  check("and hands the buttons back",
        env.buildEls.every(one => one.disabled === false),
        env.buildEls.map(one => one.disabled).join());
}

// 30b. Sizes beyond the four steps are kept. A CJK family wants 8, 10 and 12
//      for the interface as well as its reading sizes, and a control with
//      nowhere to put them would drop them on the next save.
{
  const env = await loaded(fakeStorage(), sixSizes());
  const boxes = (name) => env.exportForm.elements[name].value;
  check("the first four fill the steps",
        ["size1", "size2", "size3", "size4"].map(boxes).join() === "8,10,12,14",
        ["size1", "size2", "size3", "size4"].map(boxes).join());
  check("and the rest are held rather than dropped",
        boxes("size_more") === "16 18", boxes("size_more"));
  check("in a row that is only there when there are any",
        env.sandbox.document.getElementById("more-row").hidden === false);

  env.exportForm.elements.size1.value = "9";
  env.exportForm.edit("size1");
  await env.save.click();
  check("a save writes the whole list back, in order",
        env.fetches.saves.at(-1).export.sizes === "9 10 12 14 16 18",
        env.fetches.saves.at(-1).export.sizes);
}

// 30b2. And the same for the second family, which has four boxes of its own.
{
  const env = await loaded(fakeStorage(), sixSizes("sizes_mod"));
  const fields = env.exportForm.elements;
  check("the second family's overflow is held too",
        fields.mod_more.value === "16 18", fields.mod_more.value);
  check("in a row that is only there when there is something in it",
        env.sandbox.document.getElementById("mod-more-row").hidden === false);

  fields.mod1.value = "9";
  env.exportForm.edit("mod1");
  await env.save.click();
  check("and a save writes the whole second list back",
        env.fetches.saves.at(-1).export.sizes_mod === "9 10 12 14 16 18",
        env.fetches.saves.at(-1).export.sizes_mod);
}

// 30b3. The size boxes take what the size knob can reach and nothing between
//       its steps: a size nobody could preview is one nobody could check
//       before it shipped. Snapped on the way out of the box rather than on
//       every keystroke, or correcting 13.3 would fight somebody typing
//       13.375.
{
  const env = await loaded(fakeStorage());
  const fields = env.exportForm.elements;
  const leave = (name, typed) => {
    fields[name].value = typed;
    env.exportForm.edit(name);
    env.exportForm.leave(name);
    return fields[name].value;
  };
  check("a quarter point is left alone", leave("size3", "13.25") === "13.25",
        fields.size3.value);
  check("and anything between two of them lands on the nearer",
        leave("size3", "13.3") === "13.25", fields.size3.value);
  check("halfway goes up, as the label's own rounding does",
        leave("size3", "13.125") === "13.25", fields.size3.value);
  // The one that is aimed at a keyboard rather than at a mistake: 13,25 is
  // how a Russian or German layout writes it, and the config's own separator
  // is comma-or-space, where the same string is two sizes. A box holds one
  // size, so this is the only place the two can be told apart.
  check("a decimal comma is a decimal point in a box that holds one size",
        leave("size3", "13,25") === "13.25", fields.size3.value);
  check("above what the page can draw is pulled back into it",
        leave("size3", "200") === "40", fields.size3.value);
  check("and below it likewise", leave("size3", "2") === "6",
        fields.size3.value);
  check("an empty box stays empty rather than becoming a size",
        leave("size3", "") === "", fields.size3.value);
  // Handed back rather than swallowed: the save runs it through the
  // converter's own parser and names the problem, which beats a box that
  // silently empties itself.
  check("and something that is not a number is left for the save to refuse",
        leave("size3", "big") === "big", fields.size3.value);
  check("the overflow row snaps every entry, where a comma still means "
        + "\"and\"", leave("size_more", "16.3 18,20") === "16.25 18 20",
        fields.size_more.value);
  check("and the second family's boxes follow the same rule",
        leave("mod1", "15.6") === "15.5", fields.mod1.value);
}

// 30b4. What a fractional size will be called on the card. 13.25 is rasterized
//       at 13.25 and shipped as `Family_13`, because the device parses the
//       size out of the filename and cannot hold a fraction there -- so
//       without this the first place anyone learns which Font Size entry is
//       which is the device.
{
  const env = await loaded(fakeStorage());
  const fields = env.exportForm.elements;
  const note = env.sandbox.document.getElementById("ships-as");
  const modNote = env.sandbox.document.getElementById("mod-ships-as");
  // Alto opens at 12 and 13, which are their own labels.
  check("a list of whole sizes says nothing", note.hidden === true);

  fields.size3.value = "15.5";
  env.exportForm.edit("size3");
  check("a fractional size says what the device will list it as",
        note.hidden === false && note.textContent
          === "15.5 ships as Alto_16, which is what the device lists it as.",
        note.textContent);
  check("and it is not a warning", note.classes.has("warn") === false);

  fields.size4.value = "17.25";
  env.exportForm.edit("size4");
  check("two of them are both named", note.textContent
        === "15.5 ships as Alto_16, 17.25 as Alto_17, which is what the "
          + "device lists them as.", note.textContent);

  fields.name.value = "Alt";
  env.exportForm.edit("name");
  check("the file follows the name being typed, saved or not",
        note.textContent.includes("Alt_16"), note.textContent);
  fields.name.value = "Alto";
  env.exportForm.edit("name");

  // Quarter points make this easy to walk into -- 15.5 and 15.75 are both 16 --
  // and the save refuses it, so without the note the only way to find out is a
  // press of Save that does nothing.
  fields.size4.value = "15.75";
  env.exportForm.edit("size4");
  check("two sizes landing on one name are a warning, ahead of the refusal",
        note.classes.has("warn") === true && note.textContent
          === "15.5 and 15.75 both ship as Alto_16, so they cannot both be "
            + "built. Saving will refuse this.", note.textContent);
  fields.size4.value = "";
  env.exportForm.edit("size4");
  check("and clearing one of them takes the warning down",
        note.classes.has("warn") === false && note.hidden === false,
        note.textContent);

  // The second family is named after the first, so its note has to be.
  fields.mod1.value = "13.5";
  env.exportForm.edit("mod1");
  check("the second family gets its own note, under its own name",
        modNote.textContent
          === "13.5 ships as AltoMod_14, which is what the device lists it "
            + "as.", modNote.textContent);
  fields.mod_suffix.value = "Alt";
  env.exportForm.edit("mod_suffix");
  check("which follows its suffix", modNote.textContent.includes("AltoAlt_14"),
        modNote.textContent);

  // The heading and this note name the same second family or the panel is
  // saying two things at once, and a save posts the suffix trimmed.
  const heading = env.sandbox.document.getElementById("mod-name");
  fields.mod_suffix.value = " ";
  env.exportForm.edit("mod_suffix");
  check("and a suffix of nothing but space is the default in both places",
        heading.textContent === "AltoMod"
        && modNote.textContent.includes("AltoMod_14"),
        `${heading.textContent} | ${modNote.textContent}`);
  fields.mod_suffix.value = "";
  env.exportForm.edit("mod_suffix");

  // It is a fact about the family on the panel, so switching family replaces
  // it rather than leaving the last one's answer standing.
  env.family.choose("Sample");
  check("and a family whose sizes are whole clears it",
        note.hidden === true && modNote.hidden === true,
        `${note.textContent} | ${modNote.textContent}`);
}

// 30b5. A size box says what will ship and the knob on the left says what you
//       are looking at, which used to mean typing each shipped size into the
//       knob by hand to judge it. A box's title moves the knob to what the box
//       holds. The knob is a view setting, so nothing about the config moves
//       with it.
{
  const env = await loaded(fakeStorage());
  check("the family opens with its own sizes in the boxes",
        env.exportForm.elements.size1.value === "12", env.exportForm.elements.size1.value);
  check("and the knob at the size the page is drawn at",
        env.byName.size.value === "13", env.byName.size.value);

  env.exportForm.preview("size1");
  await settle();
  check("pressing a box's title shows the page at that size",
        env.byName.size.value === "12", env.byName.size.value);
  check("and draws it", env.fetches.bodies.at(-1).size === 12,
        JSON.stringify(env.fetches.bodies.at(-1).size));
  check("without touching what the config says",
        env.save.disabled === true && env.fetches.saves.length === 0,
        `${env.save.disabled}/${env.fetches.saves.length}`);

  // What the box would hold once it snapped, since the press can come before
  // the box has been left. Anything outside the knob's range comes back into
  // it the same way.
  env.exportForm.elements.size2.value = "13.3";
  env.exportForm.edit("size2");
  env.exportForm.preview("size2");
  check("a size still being typed is shown as the box will hold it",
        env.byName.size.value === "13.25", env.byName.size.value);

  env.exportForm.elements.mod1.value = "9";
  env.exportForm.edit("mod1");
  env.exportForm.preview("mod1");
  check("the second family's boxes do it too",
        env.byName.size.value === "9", env.byName.size.value);

  // The second family starts with no sizes at all, so most of its boxes are
  // empty -- and an empty box has no size to show.
  env.exportForm.preview("mod4");
  check("and an empty box leaves the knob where it was",
        env.byName.size.value === "9", env.byName.size.value);
}

// 30c. The second family: the same faces at other sizes, listed beside this one
//      on the device. Its suffix names it, so it is dead until there is one.
{
  const env = await loaded(fakeStorage());
  const suffix = env.exportForm.elements.mod_suffix;
  const modName = env.sandbox.document.getElementById("mod-name");
  check("a family with no second one leaves the row empty",
        ["mod1", "mod2", "mod3", "mod4"]
          .every(name => env.exportForm.elements[name].value === ""));
  check("and its suffix is out of reach", suffix.disabled === true);
  check("with nothing named yet", modName.textContent === "a second family",
        modName.textContent);

  env.exportForm.elements.mod1.value = "13";
  env.exportForm.edit("mod1");
  check("a size turns the suffix on", suffix.disabled === false);
  suffix.value = "Alt";
  env.exportForm.edit("mod_suffix");
  check("and the panel says what the second family will be called",
        modName.textContent === "AltoAlt", modName.textContent);

  await env.save.click();
  const posted = env.fetches.saves.at(-1).export;
  check("the save carries both", posted.sizes_mod === "13" &&
        posted.mod_suffix === "Alt", JSON.stringify(posted));
  check("and the first family's own sizes are untouched",
        posted.sizes === "12 13", posted.sizes);
}

// 30d. What the family is called once it is built. A source family can be
//      called whatever its files are called and the reader's Font list is a
//      phone-sized screen, so the name is a field of its own -- and everything
//      on this page is keyed by it, which is what a save has to move.
{
  const store = fakeStorage();
  const env = await loaded(store);
  const nameBox = env.exportForm.elements.name;
  const modName = env.sandbox.document.getElementById("mod-name");
  const entries = env.modules.get("family.js").familyEntries;
  check("the box opens on what the family builds as",
        nameBox.value === "Alto", nameBox.value);

  // A family falling back to this one holds it by the name it builds under,
  // which is the name about to change.
  entries.get("Sample").export.fallback1 = "Alto";

  nameBox.value = "Alt";
  env.exportForm.edit("name");
  check("typing a name offers a save", env.save.disabled === false);
  env.exportForm.elements.mod1.value = "13";
  env.exportForm.edit("mod1");
  check("and the second family is named after it before it is saved",
        modName.textContent === "AltMod", modName.textContent);

  await env.save.click();
  check("the save carries the name",
        env.fetches.saves.at(-1).export.name === "Alt",
        JSON.stringify(env.fetches.saves.at(-1).export));
  check("the picker follows it", env.family.value === "Alt", env.family.value);
  check("under the label it had", env.family.selectedOptions[0].textContent
        === "Alt", env.family.selectedOptions[0].textContent);
  check("the entry moves with it, since everything here is keyed by the name",
        entries.has("Alt") && !entries.has("Alto"),
        [...entries.keys()].join());
  check("and so does a fallback that pointed at the old name",
        entries.get("Sample").export.fallback1 === "Alt",
        entries.get("Sample").export.fallback1);
  check("and it is remembered under the new name, or the next visit asks for "
        + "a family the server no longer has",
        store.data["crossglyph.family"] === "Alt",
        store.data["crossglyph.family"]);
  check("with nothing left to save", env.save.disabled === true);

  // The proof of the line above: a picker refuses a value none of its options
  // carries, so a fallback left on the old name would blank -- and the panel
  // would then offer to save that emptiness over a config nobody touched.
  env.family.choose("Sample");
  check("the family that falls back to it opens on the right one",
        env.exportForm.elements.fallback1.value === "Alt",
        env.exportForm.elements.fallback1.value);
  check("with nothing of its own to save either",
        env.save.disabled === true);
  env.family.choose("Alt");

  // The strip that makes it a filename is the server's, and the page shows
  // what landed rather than what was typed.
  nameBox.value = "My Font!";
  env.exportForm.edit("name");
  await env.save.click();
  check("a name that could not be a filename comes back stripped",
        nameBox.value === "MyFont", nameBox.value);
  check("and the picker takes the same one", env.family.value === "MyFont",
        env.family.value);
}

// 31. The thresholds control: one list with both presets on it, and a config
//     carrying its own triple offered as a third rather than blanked -- a
//     select refuses a value none of its options has, and would then save it
//     blank.
{
  const env = await loaded(fakeStorage());
  check("the saved triple is what the control shows",
        env.byName.thresholds.value === "3,6,10", env.byName.thresholds.value);

  env.family.choose("Sample");
  check("a config's own triple is offered rather than dropped",
        env.byName.thresholds.value === "2,5,9", env.byName.thresholds.value);
  check("as an option beside the two presets",
        env.byName.thresholds.options.map(o => o.value).join()
          === "4,8,12,3,6,10,2,5,9",
        env.byName.thresholds.options.map(o => o.value).join());

  env.family.choose("Alto");
  check("and the custom one goes when the family that had it does",
        env.byName.thresholds.options.map(o => o.value).join()
          === "4,8,12,3,6,10",
        env.byName.thresholds.options.map(o => o.value).join());
}

// 32. The bundled faces are not vendored, so the panel offers to fetch them
//     -- and only when they are not already somewhere.
{
  const env = await loaded(fakeStorage());
  check("with the faces present there is nothing to offer",
        env.sandbox.document.getElementById("fetch").hidden === true);

  const bare = await loaded(fakeStorage(), { ...DEFAULTS, fallbacks: "" });
  check("and without them the offer appears",
        bare.sandbox.document.getElementById("fetch").hidden === false);
  check("with the state said in words",
        bare.sandbox.document.getElementById("have-fallbacks").textContent
          === "not fetched yet",
        bare.sandbox.document.getElementById("have-fallbacks").textContent);
}

// 40. Variable fonts. One file is several faces, so which face each slot is
//     drawn at is a choice the page has to be able to make -- and it is the
//     font's own named instances that are worth offering, not a bare number.
{
  const env = await loaded(fakeStorage());
  const box = env.sandbox.document.getElementById("variable");
  check("a static family shows no axis controls", box.hidden === true,
        String(box.hidden));

  env.family.choose("Vari");
  await settle();
  check("a variable one shows them", box.hidden === false, String(box.hidden));
  check("with the font's own instances on the pickers",
        env.byName.axis_text.options.map(o => o.textContent).join() ===
          "Light 300,Regular 400,Bold 700,Black 900",
        env.byName.axis_text.options.map(o => o.textContent).join());
  check("each opening at the weight that slot is built at",
        env.byName.axis_text.value === "400" &&
        env.byName.axis_bold.value === "700",
        `${env.byName.axis_text.value}/${env.byName.axis_bold.value}`);
  check("and a row for every other axis the font declares",
        env.sandbox.document.getElementById("axis-rows").children.length === 1,
        String(env.sandbox.document.getElementById("axis-rows").children.length));
  check("with nothing to save yet", env.save.disabled === true,
        String(env.save.disabled));

  const rendersBefore = env.fetches.render;
  env.byName.axis_text.value = "900";
  env.byName.axis_text.on.change();
  await settle();
  check("moving a weight draws the page again",
        env.fetches.render > rendersBefore,
        `${rendersBefore} -> ${env.fetches.render}`);
  check("and carries the weights, not the tuning",
        env.fetches.bodies.at(-1).axes.text === 900 &&
        env.fetches.bodies.at(-1).axes.bold === 700 &&
        env.fetches.bodies.at(-1).tuning.axis_text === undefined,
        JSON.stringify(env.fetches.bodies.at(-1).axes));
  check("and offers a save", env.save.disabled === false,
        String(env.save.disabled));

  // Compared against the config, not remembered: putting a weight back is not
  // a change, however it got there.
  env.byName.axis_text.value = "400";
  env.byName.axis_text.on.change();
  await settle();
  check("moving it back to what the config says offers nothing",
        env.save.disabled === true, String(env.save.disabled));

  // Reset is one of the ways it can get there. The pickers are filled from the
  // font's instances rather than declared in the markup, so resetting them to
  // a markup default would land on the lightest weight the font has.
  env.byName.axis_text.value = "900";
  env.byName.axis_text.on.change();
  await settle();
  env.clicks.font();
  await settle();
  check("resetting the font knobs puts the weights back too",
        env.byName.axis_text.value === "400" &&
        env.byName.axis_bold.value === "700",
        `${env.byName.axis_text.value}/${env.byName.axis_bold.value}`);
  check("and leaves nothing to save",
        env.save.disabled === true, String(env.save.disabled));

  env.byName.axis_text.value = "900";
  env.byName.axis_text.on.change();
  await settle();
  await env.save.click();
  check("saving writes the weights",
        env.fetches.saves.at(-1).axes.text === 900,
        JSON.stringify(env.fetches.saves.at(-1).axes));
  check("and leaves the panel clean against the file it just wrote",
        env.save.disabled === true, String(env.save.disabled));
  // And the file now says 900, so 400 is the change from here.
  env.byName.axis_text.value = "400";
  env.byName.axis_text.on.change();
  await settle();
  check("with the saved weight as the new baseline",
        env.save.disabled === false, String(env.save.disabled));
}

// 40a. And switching away puts the controls back out of sight, rather than
//      leaving one family's instances on another family's page.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Vari");
  await settle();
  env.family.choose("Alto");
  await settle();
  const box = env.sandbox.document.getElementById("variable");
  check("a static family after a variable one shows no axis controls",
        box.hidden === true, String(box.hidden));
  check("and posts no axes at all",
        Object.keys(env.fetches.bodies.at(-1).axes).length === 0,
        JSON.stringify(env.fetches.bodies.at(-1).axes));
}

// 40b. A slider is a burst of events, not one. The core draws one page at a
//      time, so a path that asks for a page per event queues them and the page
//      falls minutes behind the knob -- which is what an axis row wired to its
//      own redraw instead of the shared one did.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Vari");
  await settle();
  const row = env.sandbox.document.getElementById("axis-rows").children[0];
  const [minus, field, plus] = row.children[2].children;

  check("a built axis row names its field for the label",
        row.children[0].htmlFor === "axis-wdth" &&
        row.children[2].children[1].id === "axis-wdth",
        `${row.children[0].htmlFor}/${row.children[2].children[1].id}`);
  check("a built axis row has a stepper either side of its field",
        minus.textContent === "−" && plus.textContent === "+" &&
        field.type === "number",
        [minus.textContent, field.type, plus.textContent].join());

  const slider = row.children[1];
  const before = env.fetches.render;
  // A drag: twenty events in one tick, as a real one is.
  for (let at = 88; at <= 107; at++) {
    slider.value = String(at);
    slider.on.input();
  }
  check("and the field follows the slider through it",
        field.value === "107", field.value);
  await settle();
  check("but a drag asks for one page, not one per event",
        env.fetches.render === before + 1,
        `${before} -> ${env.fetches.render}`);
  check("carrying where the drag ended",
        env.fetches.bodies.at(-1).axes.wdth === 107,
        JSON.stringify(env.fetches.bodies.at(-1).axes));

  // The stepper moves it the same way, through the same coalescing.
  const stepped = env.fetches.render;
  minus.on.pointerdown({ shiftKey: false });
  minus.on.pointerdown({ shiftKey: false });
  await settle();
  check("the stepper steps by the axis step",
        field.value === "105", field.value);
  check("and two presses are still one page",
        env.fetches.render === stepped + 1,
        `${stepped} -> ${env.fetches.render}`);
}

// 40b2. An axis row is built from the font and has no markup to declare a
//       coarse press in, so it derives one: a round number sized off the range,
//       sixteen presses across whatever the axis turns out to be. wdth spans 25
//       in ones, which makes it two.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Vari");
  await settle();
  const row = env.sandbox.document.getElementById("axis-rows").children[0];
  const [minus, field, plus] = row.children[2].children;

  plus.on.pointerdown({ shiftKey: true });
  check("a coarse press on a built row takes the derived step",
        field.value === "102", field.value);
  minus.on.pointerdown({ shiftKey: false });
  check("and a bare one still takes the axis step",
        field.value === "101", field.value);
}

// 40c. Reset font knobs leaves the axis controls where they are. They are not
//      knobs: they say which face each slot is, and a font's own instances are
//      the only answer to that -- there is no factory value to go back to.
//      Reset picks the first option of a select it does not recognise, which
//      here is the lightest weight the font carries.
{
  const env = await loaded(fakeStorage());
  env.family.choose("Vari");
  await settle();
  env.byName.gamma.value = "2.4";
  env.listeners.input({ target: env.byName.gamma });
  await settle();

  env.clicks.font();
  await settle();
  check("Reset font knobs puts a tuning knob back",
        env.byName.gamma.value === "1", env.byName.gamma.value);
  check("and leaves the weights alone",
        env.byName.axis_text.value === "400" &&
        env.byName.axis_bold.value === "700",
        `${env.byName.axis_text.value}/${env.byName.axis_bold.value}`);
  check("so the panel is still clean against its config",
        env.save.disabled === true, String(env.save.disabled));
}


// 40d. A numeric axis is a tuning control with the same two comparisons as a
//      declared knob: the config is its first way back, and the font's own
//      axis default is what Untuned means.
{
  const defaults = JSON.parse(JSON.stringify(DEFAULTS));
  const variable = defaults.families.find(family => family.name === "Vari").variable;
  variable.other.wdth = 105;
  const env = await loaded(fakeStorage(), defaults);
  env.family.choose("Vari");
  await settle();

  let row = env.sandbox.document.getElementById("axis-rows").children[0];
  let slider = row.children[1], field = row.children[2].children[1];
  let arrow = row.children[3];
  check("an axis opens on the value its config declares",
        field.value === "105", field.value);
  check("and offers its font default as the stock comparison",
        arrow.hidden === false && /stock value/.test(arrow.title), arrow.title);

  field.value = "110";
  env.listeners.input({target: field});
  await settle();
  check("changing an axis offers a per-row way back to the config",
        arrow.hidden === false && /what the config has/.test(arrow.title),
        arrow.title);
  check("and keeps its slider synchronized",
        slider.value === "110", `${slider.value}/${field.value}`);
  check("and offers to save", env.save.disabled === false,
        String(env.save.disabled));

  arrow.on.click();
  await settle();
  check("the axis arrow shows the config value",
        field.value === "105" && arrow.dataset.state === "on",
        `${field.value}/${arrow.dataset.state}`);
  env.compare.fire();
  await settle();
  check("Untuned can sit above an axis already set aside",
        field.value === "100" && arrow.dataset.state === "on" &&
          /stock value/.test(arrow.title),
        `${field.value}/${arrow.dataset.state}/${arrow.title}`);
  env.compare.fire();
  await settle();
  check("leaving Untuned returns to the visible config value",
        field.value === "105" && arrow.dataset.state === "on",
        `${field.value}/${arrow.dataset.state}`);
  arrow.on.click();
  await settle();
  check("and puts the edited value back",
        field.value === "110" && arrow.dataset.state === "off",
        `${field.value}/${arrow.dataset.state}`);

  await env.save.click();
  check("saving makes the edited axis the config baseline",
        env.fetches.saves.at(-1).axes.wdth === 110 &&
          env.save.disabled === true &&
          /stock value/.test(arrow.title),
        `${JSON.stringify(env.fetches.saves.at(-1).axes)}/${arrow.title}`);

  env.compare.fire();
  await settle();
  check("Untuned shows the font's own axis default, not the config",
        field.value === "100", field.value);
  env.compare.fire();
  await settle();
  check("leaving Untuned restores the edited axis value",
        field.value === "110", field.value);

  field.value = "105";
  env.listeners.input({target: field});
  await settle();
  env.clicks.font();
  await settle();
  row = env.sandbox.document.getElementById("axis-rows").children[0];
  field = row.children[2].children[1];
  arrow = row.children[3];
  check("Reset font knobs restores the saved axis baseline",
        field.value === "110" && env.save.disabled === true, field.value);
  check("and the rebuilt row still offers its stock comparison",
        arrow.hidden === false && /stock value/.test(arrow.title), arrow.title);
}

// 41. A render that fails says so over the sheet. A blank page with the reason
//     under the text box is a page nobody reads: the eye is on the specimen,
//     so that is where the sentence goes.
{
  const env = await loaded(fakeStorage(), undefined,
                           {renderFails: {status: 503,
                                          body: '{"detail":"the bundled fallback faces are not here yet"}'}});
  check("a failed render shows the notice over the page",
        env.pageError.hidden === false, String(env.pageError.hidden));
  check("with a headline that says which kind of failure it was",
        env.pageError.parts.what.textContent === "The page cannot be drawn yet.",
        env.pageError.parts.what.textContent);
  check("and the server's own sentence, out of its JSON envelope",
        env.pageError.parts.why.textContent ===
          "the bundled fallback faces are not here yet",
        env.pageError.parts.why.textContent);
  check("the status line carries the code rather than the whole body",
        env.status.textContent === "503", env.status.textContent);
}

// 41a. A refused setting is a different sentence, because it is a different
//      thing to do something about.
{
  const env = await loaded(fakeStorage(), undefined,
                           {renderFails: {status: 422, body: "gamma: too large"}});
  check("a refused knob says so",
        env.pageError.parts.what.textContent === "That setting was refused.",
        env.pageError.parts.what.textContent);
  check("and a body that is not JSON is shown as it came",
        env.pageError.parts.why.textContent === "gamma: too large",
        env.pageError.parts.why.textContent);
}

// 41b. A server that has stopped answers nothing at all. There is no status
//      code to report, and the reader needs to know it is not their setting.
{
  const env = await loaded(fakeStorage(), undefined, {renderThrows: true});
  check("a server that is not answering says that, not a stack trace",
        env.pageError.parts.what.textContent ===
          "The preview server is not answering.",
        env.pageError.parts.what.textContent);
  check("and says what to do about it",
        env.pageError.parts.why.textContent.includes("Try again"),
        env.pageError.parts.why.textContent);
}

// 41c. And it clears itself: a page that came back must not keep a stale
//      complaint over it.
{
  const env = await loaded(fakeStorage(), undefined, {renderOk: true});
  env.pageError.hidden = false;
  env.byName.gamma.value = "1.4";
  env.listeners.input({ target: env.byName.gamma });
  await settle();
  check("a render that worked takes the notice away",
        env.pageError.hidden === true, String(env.pageError.hidden));
}

// 41d. A newer render can abort the old one after its headers have arrived.
//      Reading the body is part of the request too: neither a PNG nor an error
//      body interrupted there may escape as an unhandled rejection.
for (const deferred of [
  {ok: true, label: "PNG"},
  {ok: false, status: 503, label: "error"},
]) {
  const env = await loaded(fakeStorage(), undefined,
                           {deferredRenderBodies: [deferred], renderOk: true});
  check(`the first ${deferred.label} body is being read`,
        env.fetches.bodyReads.length === 1);
  env.byName.gamma.value = "1.4";
  env.listeners.input({target: env.byName.gamma});
  await settle();
  await settle();
  check(`aborting the ${deferred.label} body lets the newer page paint`,
        env.device.canvas.painted?.source?.fresh === true &&
        env.pageError.hidden === true,
        `${JSON.stringify(env.device.canvas.painted)} / ${env.pageError.hidden}`);
}

// 41e. Aborting is advisory once a response body is already completing. If an
//      old read resolves anyway, it must stop before decoding or painting over
//      the newer page.
{
  const env = await loaded(fakeStorage(), undefined, {
    deferredRenderBodies: [{ok: true, ignoreAbort: true}], renderOk: true,
  });
  env.byName.gamma.value = "1.4";
  env.listeners.input({target: env.byName.gamma});
  await settle();
  await settle();
  const newest = env.device.canvas.painted;
  env.fetches.bodyReads[0].resolve({stale: true});
  await settle();
  check("a stale body cannot decode or paint over the newer page",
        env.device.canvas.painted === newest &&
        env.fetches.bitmaps.length === 1,
        `${JSON.stringify(env.device.canvas.painted)} / `
        + `${env.fetches.bitmaps.length}`);
}

// 42. The language only says which patterns hyphenate, so with the switch
//     under it off it draws the identical page. Greyed, the row says that
//     before it is turned rather than after.
{
  const env = await loaded(fakeStorage());
  check("with hyphenation off the language is not offered",
        env.byName.language.disabled === true, String(env.byName.language.disabled));

  env.byName.hyphenation.checked = true;
  env.byName.hyphenation.on.change();
  check("turning it on offers the language",
        env.byName.language.disabled === false, String(env.byName.language.disabled));

  env.clicks.page();
  check("and resetting the page settings takes it back",
        env.byName.language.disabled === true, String(env.byName.language.disabled));
}

// 42b. And a remembered `hyphenation` has to reach it too: the state is
//      restored from storage, which fires nothing.
{
  const env = await loaded(fakeStorage({
    "crossglyph.page": JSON.stringify({ hyphenation: true, language: "en" }) }));
  check("a remembered switch leaves the language offered",
        env.byName.language.disabled === false, String(env.byName.language.disabled));
}

// 43. The progress bar. A build is minutes with the fallbacks on, and the
//     stream carries a count from its first line, so the panel says how far
//     rather than that it is working.
{
  const env = await loaded(fakeStorage());
  const {progressBar} = env.modules.get("progress.js");
  const progress = progressBar(env.progress);

  // Before the plan arrives there is no total. A progressbar says that by
  // carrying no aria-valuenow, and the rule sweeps instead of sitting empty.
  progress.start("planning every family…");
  check("planning shows the bar", env.progress.hidden === false);
  check("sweeping rather than claiming a fraction it has not got",
        env.bar.classes.has("waiting") && !("aria-valuenow" in env.bar.attrs),
        JSON.stringify([...env.bar.classes]));

  progress.show(3, 12, "Alto 14");
  check("a counted step fills the rule", env.barFill.style.width === "25%",
        env.barFill.style.width);
  check("and stops sweeping", env.bar.classes.has("waiting") === false);
  check("with the count where a screen reader finds it too",
        env.bar.attrs["aria-valuenow"] === "3"
        && env.bar.attrs["aria-valuemax"] === "12",
        JSON.stringify(env.bar.attrs));

  progress.end();
  check("and it goes when the build does", env.progress.hidden === true);
}

// 43a. The build's own bar, which is not that one. It is a rule in the foot of
//      the export panel, in the tone that foot's border is drawn in, so at
//      rest it is the divider under the buttons and a run only fills it. The
//      foot is the one card on the page that has to hold still: taking the bar
//      out of the document between runs would change its height at both ends
//      of every build. Idle it is also nothing to a screen reader, since a
//      progressbar sitting at no value all day is a control that is not there.
{
  const env = await loaded(fakeStorage());
  const {progressBar} = env.modules.get("progress.js");
  const row = env.progress;
  const progress = progressBar(row, undefined, {keep: true});

  // It starts out of nobody's way, which the markup says rather than this: the
  // bar is in the document from the first paint, and nothing has run yet to
  // put an attribute on it. test_the_build_bar_is_a_rule_until_it_runs has it.
  progress.start("planning Alto…");
  check("a run never touches the row's own hidden",
        row.hidden === true, String(row.hidden));
  check("and says it is running on the row instead",
        row.dataset.running === "", JSON.stringify(row.dataset));
  check("with the bar exposed again while it has something to say",
        !("aria-hidden" in env.bar.attrs), JSON.stringify(env.bar.attrs));

  progress.show(3, 12, "Alto 14");
  progress.end();
  check("the end puts the flag down rather than the row",
        row.dataset.running === undefined && row.hidden === true,
        `${row.dataset.running} ${row.hidden}`);
  check("and clears the line, since it is still on screen to be read",
        env.progressWhat.steps.at(-1) === "" &&
        env.progressCount.steps.at(-1) === "",
        JSON.stringify([env.progressWhat.steps.at(-1),
                        env.progressCount.steps.at(-1)]));
  check("leaving a rule and not a progressbar at nothing",
        env.bar.attrs["aria-hidden"] === "true" &&
        !("aria-valuenow" in env.bar.attrs), JSON.stringify(env.bar.attrs));
}

// 43b. The estimate, which is arithmetic and worth asking directly. It is
//      held back rather than shown wrong: the first size pays the one-off
//      costs of the whole run, so an estimate drawn from it is out by a
//      factor, and this is the one screen somebody is waiting at.
{
  const env = await loaded(fakeStorage());
  const {timeLeft, spellDuration} = env.modules.get("progress.js");
  check("nothing from one size, however long it took",
        timeLeft(1, 10, 60000) === "", timeLeft(1, 10, 60000));
  check("nothing in the first seconds either",
        timeLeft(2, 10, 3000) === "", timeLeft(2, 10, 3000));
  check("then what the sizes so far say the rest will cost",
        timeLeft(2, 10, 10000) === "40s left", timeLeft(2, 10, 10000));
  check("and nothing at the end, where there is no rest",
        timeLeft(10, 10, 60000) === "", timeLeft(10, 10, 60000));
  check("minutes read as minutes", spellDuration(130) === "2m 10s",
        spellDuration(130));
  check("and a round one drops the seconds", spellDuration(120) === "2m",
        spellDuration(120));
}

// 44. A rebuild. Shift is what this page already means by "more", so it is a
//     modifier on the button that builds rather than a third button, and the
//     buttons say what they will do for as long as it is held.
{
  const env = await loaded(fakeStorage());
  const [build, buildAll] = env.buildEls;
  check("at rest they say what they do",
        [build.textContent, buildAll.textContent].join() === "Build,Build all",
        [build.textContent, buildAll.textContent].join());

  for (const listener of env.keys) listener({ key: "Shift" });
  check("holding shift says what it would do instead",
        [build.textContent, buildAll.textContent].join() === "Rebuild,Rebuild all",
        [build.textContent, buildAll.textContent].join());

  await env.builds.one({ shiftKey: true });
  check("and the press asks for one", env.fetches.builds.at(-1).force === true,
        JSON.stringify(env.fetches.builds.at(-1)));

  for (const listener of env.keyups) listener({ key: "Shift" });
  check("letting go puts them back",
        [build.textContent, buildAll.textContent].join() === "Build,Build all",
        [build.textContent, buildAll.textContent].join());

  await env.builds.one();
  check("a plain press builds only what changed",
        env.fetches.builds.at(-1).force === false,
        JSON.stringify(env.fetches.builds.at(-1)));
}

// 44b. A build that ends while the key is down: the buttons are out, so the
//      keyup lands on nothing and the labels would stay saying "Rebuild".
{
  const env = await loaded(fakeStorage());
  for (const listener of env.keys) listener({ key: "Shift" });
  await env.builds.all({ shiftKey: true });
  check("a finished build leaves the buttons saying what a press does now",
        env.buildEls.map(one => one.textContent).join() === "Build,Build all",
        env.buildEls.map(one => one.textContent).join());
}

// 45. Press and hold on the sheet, which is the gesture every photo editor
//     uses for before and after. A look rather than a change of state.
{
  const env = await loaded(fakeStorage());
  const untuned = () => env.compare.getAttribute("aria-pressed") === "true";
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });

  env.sheet.press();
  check("holding the page shows it untuned", untuned() === true);
  check("and the knob is at what the converter does with no config",
        env.byName.gamma.value === "1", env.byName.gamma.value);

  env.sheet.release();
  check("letting go puts the tuning back", untuned() === false);
  check("and the knob with it", env.byName.gamma.value === "2.5",
        env.byName.gamma.value);

  // Dragging off the sheet gets no pointerup there, so leaving has to count as
  // letting go -- otherwise the page stays untuned with nothing holding it.
  env.sheet.press();
  env.sheet.release("pointerleave");
  check("and so does dragging off it", untuned() === false);

  // A right-click is a menu, not a comparison.
  env.sheet.press(2);
  check("the other buttons are not this gesture", untuned() === false);
}

// 45b. Held over a page already set to untuned, the release must not leave it
//      tuned: the toggle is somebody's state and the hold is only a look.
{
  const env = await loaded(fakeStorage());
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });
  env.compare.fire();
  const untuned = () => env.compare.getAttribute("aria-pressed") === "true";
  check("the toggle is on to begin with", untuned() === true);

  env.sheet.press();
  env.sheet.release();
  check("and a hold over it leaves it where it was", untuned() === true);
}

// 46. Night mode is a page knob like the rest: it posts under `page`, it is
//     remembered, and it is the reader's setting rather than the font's.
{
  const store = fakeStorage();
  const env = await loaded(store);
  const last = () => env.fetches.bodies.at(-1);

  env.byName.inverted.checked = true;
  env.listeners.input({ target: env.byName.inverted });
  await settle();
  check("it reaches the render under the page settings",
        last().page.inverted === true, JSON.stringify(last().page));
  check("and is remembered like the reader's other settings",
        JSON.parse(store.data["crossglyph.page"]).inverted === true,
        store.data["crossglyph.page"]);
  check("without touching the tuning, which is the font's",
        !("inverted" in last().tuning), JSON.stringify(last().tuning));

  env.clicks.page();
  check("and Reset page settings puts it back",
        env.byName.inverted.checked === false,
        String(env.byName.inverted.checked));
}

// 47. The sheet is blank until there is a page on it: the canvas starts
//     transparent and is shown when the first page lands.
{
  // The default render never answers, which is the state a reload is in
  // until the server has drawn: the sheet is blank paper.
  const waiting = await loaded(fakeStorage());
  check("nothing is shown before a page has been drawn",
        waiting.device.canvas.classes.has("shown") === false,
        JSON.stringify([...waiting.device.canvas.classes]));

  const env = await loaded(fakeStorage(), undefined, {renderOk: true});
  check("and the first page that arrives puts it up",
        env.device.canvas.classes.has("shown") === true,
        JSON.stringify([...env.device.canvas.classes]));
}

// 47b. A render that failed leaves it blank rather than showing an empty
//      sheet as though that were the answer.
{
  const env = await loaded(fakeStorage(), undefined,
                           {renderFails: {status: 503, body: "no faces yet"}});
  check("a refused page shows nothing on the sheet",
        env.device.canvas.classes.has("shown") === false,
        JSON.stringify([...env.device.canvas.classes]));
}

// --- the sample text presets ----------------------------------------------

// 48. A specimen you cannot read says nothing about a font you are choosing,
//     so a first visit opens on a language the browser says you have.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["de-AT", "en"] });
  check("a first visit opens on the browser's language",
        env.sample.value === "de", env.sample.value);
  check("with that language's words in the box",
        env.form.elements.text.value.startsWith("Victor jagt"),
        env.form.elements.text.value.slice(0, 20));
  check("and hyphenates with its patterns",
        env.byName.language.value === "de", env.byName.language.value);
}

// 49. The region is dropped: patterns and presets are per language, and one
//     preset per country would be a list nobody could scroll.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["ru-BY"] });
  check("a region falls back to its language",
        env.sample.value === "ru", env.sample.value);
}

// 50. Chinese is the exception: it is chosen by script and a browser reports a
//     country, so zh-CN and zh-TW are two different specimens.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["zh-CN"] });
  check("a Chinese country picks the script it is written in",
        env.sample.value === "zh-Hans", env.sample.value);
}

// 51. A language with a preset but no hyphenation patterns takes the specimen
//     and leaves the patterns alone. Hyphenating Japanese with English
//     patterns is a page nobody asked for.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["ja"] });
  check("Japanese opens on its own specimen",
        env.sample.value === "ja", env.sample.value);
  check("and hyphenates as English, having no patterns of its own",
        env.byName.language.value === "en", env.byName.language.value);
}

// 52. Nothing on the list matches, so English rather than an empty box.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["pt-BR", "pt"] });
  check("an unknown language opens on English",
        env.sample.value === "en", env.sample.value);
  check("and hyphenates as English too",
        env.byName.language.value === "en", env.byName.language.value);
}

// 53. Detection happens once. What you last chose is what you get, however
//     many languages the browser goes on claiming.
{
  const env = await loaded(fakeStorage({ "crossglyph.sample": "ru" }), DEFAULTS,
                           { languages: ["de-AT"] });
  check("a stored choice beats the browser",
        env.sample.value === "ru", env.sample.value);
  check("and its words are in the box",
        env.form.elements.text.value.startsWith("Съешь"),
        env.form.elements.text.value.slice(0, 12));
}

// 54. Page settings that were remembered are never overwritten by detection.
//     A language somebody chose outranks one a browser guessed.
{
  const env = await loaded(
    fakeStorage({ "crossglyph.page": JSON.stringify({ language: "ru" }) }),
    DEFAULTS, { languages: ["de-AT"] });
  check("a remembered language stands",
        env.byName.language.value === "ru", env.byName.language.value);
}

// 55. Typing while a preset is showing makes the text yours rather than
//     editing the preset, so the picker moves to Custom under your hands.
{
  const storage = fakeStorage();
  const env = await loaded(storage, DEFAULTS, { languages: ["de"] });
  env.byName.text.value = "мой текст";
  env.listeners.input({ target: env.byName.text });
  check("typing moves the picker to Custom",
        env.sample.value === "", env.sample.value);
  check("and what you typed is what is kept",
        storage.data["crossglyph.text"] === "мой текст",
        storage.data["crossglyph.text"]);
  check("with Custom remembered as the choice",
        storage.data["crossglyph.sample"] === "",
        storage.data["crossglyph.sample"]);
}

// 56. The whole point of the Custom entry: choosing a language must not cost
//     somebody the text they wrote, and coming back has to return it.
{
  const storage = fakeStorage({ "crossglyph.text": "мой текст",
                                "crossglyph.sample": "" });
  const env = await loaded(storage, DEFAULTS, { languages: ["de"] });
  check("your own text is what a stored Custom shows",
        env.form.elements.text.value === "мой текст",
        env.form.elements.text.value);

  env.sample.choose("ja");
  check("a preset replaces it in the box",
        env.form.elements.text.value.startsWith("いろは"),
        env.form.elements.text.value.slice(0, 8));
  check("but not in storage",
        storage.data["crossglyph.text"] === "мой текст",
        storage.data["crossglyph.text"]);

  env.sample.choose("");
  check("and switching back returns it",
        env.form.elements.text.value === "мой текст",
        env.form.elements.text.value);
}

// 57. Choosing a preset carries the hyphenation language with it, and that is
//     a decision rather than a guess, so it is written down.
{
  const storage = fakeStorage();
  const env = await loaded(storage, DEFAULTS, { languages: ["en"] });
  env.sample.choose("ru");
  check("a chosen preset moves the patterns with it",
        env.byName.language.value === "ru", env.byName.language.value);
  check("and that is remembered",
        JSON.parse(storage.data["crossglyph.page"]).language === "ru",
        storage.data["crossglyph.page"]);

  env.sample.choose("ja");
  check("a preset with no patterns leaves them where they were",
        env.byName.language.value === "ru", env.byName.language.value);
}

// 57a. Your own text is in a language too, and a preset drags `hyphenate as`
//      along with it. Coming back to Custom has to return the language the way
//      it returns the words, or your text is hyphenated as the last specimen
//      you happened to look at.
{
  const storage = fakeStorage({ "crossglyph.text": "eigener Text",
                                "crossglyph.sample": "" });
  const env = await loaded(storage, DEFAULTS, { languages: ["en"] });

  env.byName.language.value = "de";
  env.listeners.input({ target: env.byName.language });
  check("a language chosen for your own text is written down",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);

  env.sample.choose("ru");
  check("a preset still carries its own patterns in",
        env.byName.language.value === "ru", env.byName.language.value);
  check("and does not overwrite the one your text is in",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);

  // Nor does hyphenating a specimen some other way. That is a fact about the
  // specimen on screen, and the only reason it is not caught by the line above
  // is that choosing a preset moves the language without an event: this moves
  // it by hand, which is the way somebody actually does it.
  env.byName.language.value = "fr";
  env.listeners.input({ target: env.byName.language });
  check("hyphenating a preset by hand is not a choice about your own text",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);

  env.sample.choose("");
  check("coming back to Custom returns your text",
        env.form.elements.text.value === "eigener Text",
        env.form.elements.text.value);
  check("and the language you were reading it in",
        env.byName.language.value === "de", env.byName.language.value);
  check("which is a page setting, so it is remembered as one",
        JSON.parse(storage.data["crossglyph.page"]).language === "de",
        storage.data["crossglyph.page"]);
}

// 57b. Nothing stored for Custom means nothing to put back: whoever has never
//      chosen a language for their own text keeps whatever is showing rather
//      than being sent somewhere they never asked for.
{
  const storage = fakeStorage();
  const env = await loaded(storage, DEFAULTS, { languages: ["en"] });
  env.sample.choose("ru");
  check("the preset's patterns are in force", env.byName.language.value === "ru");
  env.sample.choose("");
  check("and Custom leaves them alone, having nothing of its own to say",
        env.byName.language.value === "ru", env.byName.language.value);
}

// 58. A detected language is a default and not a decision: Reset page settings
//     goes back to the language you read, not to whatever the markup declared.
{
  const storage = fakeStorage();
  const env = await loaded(storage, DEFAULTS, { languages: ["de-AT"] });
  check("nothing is written for a language nobody chose",
        !("crossglyph.page" in storage.data), JSON.stringify(storage.data));
  env.byName.language.value = "ru";
  env.clicks.page();
  check("and a reset goes back to it rather than to the markup",
        env.byName.language.value === "de", env.byName.language.value);
}

// 59. Every preset reaches the picker, in the order the server lists them,
//     with Custom kept at the top where it can always be found.
{
  const env = await loaded(fakeStorage(), DEFAULTS);
  check("Custom is first and the presets follow in order",
        env.sample.options.map(o => o.value).join() === ",zh-Hans,en,de,ja,ru",
        env.sample.options.map(o => o.value).join());
  check("named in their own languages",
        env.sample.options[1].textContent === "简体中文",
        env.sample.options[1].textContent);
}

// 60. A glyph nobody has takes no width on the device, so a page missing one
//     is blank where it should be rather than showing a box. The count comes
//     back on the render, and the note under the box is the only thing that
//     tells that apart from a page that failed to draw.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 7 });
  const note = env.sandbox.document.getElementById("undrawn");
  check("a page with holes in it says so", note.hidden === false);
  check("counting them", note.textContent.startsWith("7 characters have"),
        note.textContent);
  check("and saying the move that is actually left",
        note.textContent.includes("turn on bundled fallback faces"),
        note.textContent);
  // The bundled set is not the only answer, and on a family whose script no
  // Noto face covers it is not the answer at all.
  check("and that naming a family is the other way",
        note.textContent.includes("fallback 1"), note.textContent);
}

// 60a. The advice follows the state rather than reciting every move: with the
//      box on and the faces here, turning it on is not something anybody can
//      do, and telling them to would send them looking for a tick that is
//      already ticked.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 4 });
  const box = env.exportForm.elements.fallbacks;
  box.checked = true;
  env.exportForm.on.input({target: box});
  await settle();
  const note = env.sandbox.document.getElementById("undrawn");
  check("nothing about turning on a box already on",
        !note.textContent.includes("turn on"), note.textContent);
  check("and the one answer left is named",
        note.textContent.includes("needs a family that has them in fallback 1"),
        note.textContent);
}

// 60b. The other reason a page is blank, and the one with an answer: the
//      coverage would not build those characters. Said apart from the missing
//      glyph case because the fix is a tick and not a download, and the preset
//      that carries them is named rather than left to be worked out.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, uncovered: 45,
                             coverageFix: "arabic" });
  const note = env.sandbox.document.getElementById("uncovered");
  check("a page the coverage would not build says so", note.hidden === false);
  check("counting them",
        note.textContent.startsWith("45 characters are outside"),
        note.textContent);
  check("naming the tick that would carry them",
        note.textContent.includes("Tick arabic under Export"), note.textContent);
  check("and saying the built font would be blank too",
        note.textContent.includes("built font would be too"), note.textContent);
}

// 60c. Nothing to say when the coverage carries the page, which is every
//      page somebody has not misconfigured.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  check("no coverage note on a page that draws",
        env.sandbox.document.getElementById("uncovered").hidden === true);
}

// 60d. No preset carries them, so there is no tick to offer and the note says
//      what there is instead of naming nothing.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, uncovered: 2, coverageFix: "" });
  const note = env.sandbox.document.getElementById("uncovered");
  check("a range rather than a tick when no preset carries them",
        note.textContent.includes("needs a range under Export"),
        note.textContent);
}

// 61. One is not "1 characters", and the note is read by somebody already
//     puzzled by a page with a gap in it.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 1 });
  const note = env.sandbox.document.getElementById("undrawn");
  check("one of them reads as one", note.textContent.startsWith("1 character has"),
        note.textContent);
}

// 62. And nothing at all on the usual page, which is every page.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  check("a page that drew everything says nothing",
        env.sandbox.document.getElementById("undrawn").hidden === true);
}

// 63. The fallback fetch is a 20 MB download when a CJK face is in it. Without
//     a bar and a button that goes out, a press that is doing something looks
//     exactly like a press that did nothing, which is a press people repeat.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["ja"] });
  const before = env.fetches.render;
  await env.builds.fetch();
  // The redraw is scheduled rather than immediate, as every redraw here is.
  await settle();

  check("the button goes out for the download and comes back after",
        env.fetchButton.states.join() === "true,false",
        env.fetchButton.states.join());
  check("the bar ends full before it is put away",
        env.barFill.widths.includes("100%"), env.barFill.widths.join());
  // The foot it is drawn in stays: this bar is the rule under the buttons and
  // only ever goes quiet. Put away means back to no fraction and nothing said.
  check("and goes quiet when the download is done",
        env.progress.dataset.running === undefined &&
        env.barFill.style.width === "0%",
        `${env.progress.dataset.running} ${env.barFill.style.width}`);
  check("the count is in bytes, not files",
        env.progressCount.steps.some(line => line.includes("MB of")),
        env.progressCount.steps.join(" | "));
  // Past the clearing at the end, which is the bar being put down rather than
  // anything the run had to say.
  check("the last file named is the one that took the time",
        env.progressWhat.steps.filter(Boolean).at(-1).includes("CJK"),
        env.progressWhat.steps.filter(Boolean).at(-1));
  check("what landed is said afterwards",
        env.fetchNote.textContent === "13 faces", env.fetchNote.textContent);
  check("and the page redraws, since it can draw more than it could",
        env.fetches.render > before, `${before} -> ${env.fetches.render}`);
}

// 64. Which is the point of sending the text: a CJK sample cannot be drawn
//     without a face nobody ticked a coverage box for, and having to find the
//     right box first is the step this removes.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { languages: ["ja"] });
  await env.builds.fetch();
  const sent = env.fetches.fallbacks.at(-1);
  check("the fetch carries what is on the page",
        sent.text.includes("いろは"), JSON.stringify(sent.text || "").slice(0, 40));
  check("and the coverage, which is the other reason to bring one",
        typeof sent.intervals === "string", JSON.stringify(sent));
}

// 65. Nothing to download is worth saying: the button looks identical whether
//     it fetched twenty megabytes or found them already there.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { fetchSteps: [
    { event: "plan", files: 0, bytes: 0 },
    { event: "done", where: "D:\\fonts\\fallbacks", faces: 13 },
  ] });
  await env.builds.fetch();
  check("a fetch with nothing to do says so first",
        env.fetchNote.steps.includes("already fetched"),
        env.fetchNote.steps.join(" | "));
}

// 66. A download that dies half way leaves the button pressable, or the panel
//     is dead until a reload.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { fetchSteps: [
    { event: "plan", files: 2, bytes: 20000000 },
    { event: "error", error: "could not fetch the fallback faces: no route" },
  ] });
  await env.builds.fetch();
  check("a failed fetch says why", env.fetchNote.textContent.includes("no route"),
        env.fetchNote.textContent);
  check("and leaves the button pressable again",
        env.fetchButton.disabled === false, String(env.fetchButton.disabled));
  check("with the bar put down rather than stuck part full",
        env.progress.dataset.running === undefined &&
        env.barFill.style.width === "0%",
        `${env.progress.dataset.running} ${env.barFill.style.width}`);
}

// 67. Fetching the faces is half the job: the box beside them is what puts
//     them on the page and in the build. A 20 MB download that left the page
//     as blank as it was is a button that visibly did nothing.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 77, languages: ["ja"] });
  check("the box is off to begin with",
        env.exportForm.elements.fallbacks.checked === false);

  await env.builds.fetch();
  await settle();
  check("a fetch the page was waiting for turns it on",
        env.exportForm.elements.fallbacks.checked === true);
  check("and offers to save it, the way any other panel change does",
        env.save.disabled === false, String(env.save.disabled));
}

// 68. But not otherwise. A fetch pressed ahead of time is somebody stocking up,
//     not asking for their build settings to be rewritten.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  await env.builds.fetch();
  await settle();
  check("a fetch nothing was waiting for leaves the box alone",
        env.exportForm.elements.fallbacks.checked === false);
}

// 69. Somebody who typed their own text before the picker existed has a stored
//     text and no stored choice, which is exactly what a first visit looks
//     like. Detecting a language there would put a specimen over their words.
{
  const env = await loaded(fakeStorage({ "crossglyph.text": "мой текст" }),
                           DEFAULTS, { languages: ["de-AT"] });
  check("text already written keeps the box",
        env.byName.text.value === "мой текст", env.byName.text.value);
  check("with the picker saying whose it is",
        env.sample.value === "", env.sample.value);
}

// 70. And an empty box is what detection is for.
{
  const env = await loaded(fakeStorage({ "crossglyph.text": "" }), DEFAULTS,
                           { languages: ["de-AT"] });
  check("an empty box takes the browser's language",
        env.sample.value === "de", env.sample.value);
}

// 71. `reading` is the converter's `default` and a good deal more, so ticking
//     it settles other boxes. A row that says nothing about that reads as
//     several separate things a build needs.
{
  const env = await loaded(fakeStorage());
  const boxes = Object.fromEntries(
    env.presetList.querySelectorAll().map(box => [box.value, box]));

  check("a preset another tick carries whole is shown on",
        boxes.default.checked === true, String(boxes.default.checked));
  check("and turned off, there being nothing to decide",
        boxes.default.disabled === true, String(boxes.default.disabled));
  check("saying which tick carries it",
        boxes.default.title.includes("reading"), boxes.default.title);
  check("and marked so the row reads differently",
        boxes.default.parentElement.classes.has("implied"));

  // Half inside is not inside: ticking Cyrillic still adds the supplement,
  // and locking it would claim otherwise.
  // Half inside is not inside. Cyrillic is named by this config as well, so
  // it is on -- but as a choice of the reader's, still theirs to untick.
  check("a preset only partly carried stays yours to untick",
        boxes.cyrillic.disabled === false, String(boxes.cyrillic.disabled));
  check("and one nothing carries is neither ticked nor locked",
        boxes.greek.disabled === false && boxes.greek.checked === false);
}

// 72. What is carried is not written down. The config keeps the short list
//     somebody chose, not every preset those imply.
{
  const env = await loaded(fakeStorage());
  const sent = env.modules.get("export.js").exportSettings();
  check("only the chosen presets reach the config",
        sent.intervals === "reading,cyrillic", sent.intervals);
}

// 73. And untick it, and the boxes it was carrying come back to the reader.
{
  const env = await loaded(fakeStorage());
  const boxes = Object.fromEntries(
    env.presetList.querySelectorAll().map(box => [box.value, box]));
  boxes.reading.checked = false;
  env.exportForm.on.input({ target: boxes.reading });

  check("what was carried is released", boxes.default.disabled === false,
        String(boxes.default.disabled));
  check("and is no longer ticked, nothing carrying it now",
        boxes.default.checked === false, String(boxes.default.checked));
  check("with only what is still chosen written down",
        env.modules.get("export.js").exportSettings().intervals === "cyrillic",
        env.modules.get("export.js").exportSettings().intervals);
}

// 74. A tick of your own is never taken away by one that would imply it: the
//     config named it, and unticking the other has to give it back.
{
  const env = await loaded(fakeStorage());
  const boxes = Object.fromEntries(
    env.presetList.querySelectorAll().map(box => [box.value, box]));
  // Default is carried by reading. Tick it outright and it becomes a choice
  // of yours, so unticking reading later leaves it standing.
  boxes.default.disabled = false;            // as releasing reading would
  boxes.default.checked = true;
  env.exportForm.on.input({ target: boxes.default });
  boxes.reading.checked = false;
  env.exportForm.on.input({ target: boxes.reading });
  check("a tick of your own outlives the one that implied it",
        boxes.default.checked === true && boxes.default.disabled === false,
        `${boxes.default.checked} ${boxes.default.disabled}`);
}

// 75. Nothing was written, so there is no size to give. "0 built (0 B)" says
//     the same thing twice and reads like a failure.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { buildSteps: [
    { event: "plan", total: 1, out: "D:\\fonts\\cpfonts", families: ["Alto"] },
    { event: "done", out: "D:\\fonts\\cpfonts", bytes: 0, families: [
      { name: "Alto", bytes: 0, sizes: [12], built: [], skipped: [12],
        failed: [], removed: [], error: null }] },
  ] });
  await env.builds.one();
  check("a run that wrote nothing gives no size",
        env.built.textContent === "0 built, 1 already current",
        env.built.textContent);
}

// 76. The unit follows the number: a single small size is kilobytes, and
//     reading 41000 B off a card is nobody's idea of an answer.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { buildSteps: [
    { event: "plan", total: 1, out: "D:\\fonts\\cpfonts", families: ["Alto"] },
    { event: "size", family: "Alto", size: 12, done: 1, total: 1, bytes: 41000 },
    { event: "done", out: "D:\\fonts\\cpfonts", bytes: 41000, families: [
      { name: "Alto", bytes: 41000, sizes: [12], built: [12], skipped: [],
        failed: [], removed: [], error: null }] },
  ] });
  await env.builds.one();
  check("a small build reads in kilobytes",
        env.built.textContent.startsWith("1 built (41 kB),"),
        env.built.textContent);
}

// 77. A checkbox nobody has touched is not a changed knob. Its `value` reads
//     "on" and its `defaultValue` reads "" -- the markup sets neither -- so
//     anything comparing those two calls every checkbox on the page modified,
//     for good, and marks it for ever.
{
  const env = await loaded(fakeStorage());
  const mark = (name) => env.markList.find(m => m.dataset.mark === name);

  check("an untouched font checkbox is unmarked",
        mark("ligatures").hidden === true, String(mark("ligatures").hidden));
  check("nor is an untouched page checkbox marked",
        mark("hyphenation").hidden === true,
        String(mark("hyphenation").hidden));

  // And it still appears when the box really is off its default.
  env.byName.ligatures.checked = false;
  env.listeners.input({ target: env.byName.ligatures });
  check("and it appears once the box is actually moved",
        mark("ligatures").hidden === false, String(mark("ligatures").hidden));
  check("saying which way the baseline has it, since the box cannot",
        /has this on|stock, which is on/.test(mark("ligatures").title),
        mark("ligatures").title);
}

// 78. Untuned compares against the factory, so a knob already at the factory
//     has nothing to set aside. Stashing it anyway leaves an arrow claiming a
//     comparison that is not happening.
{
  const env = await loaded(fakeStorage());
  const mark = (name) => env.markList.find(m => m.dataset.mark === name);
  env.compare.fire();
  check("a checkbox already at the factory is left alone by untuned",
        mark("ligatures").hidden === true, String(mark("ligatures").hidden));
  check("and the page checkbox is not in this comparison at all",
        mark("hyphenation").hidden === true,
        String(mark("hyphenation").hidden));
  env.compare.fire();
  check("and it is still where it was afterwards",
        env.byName.ligatures.checked === true,
        String(env.byName.ligatures.checked));

  // A checkbox that has moved does go back, though, and that is worth its own
  // check: untuned walks the knob list rather than the arrows, and a checkbox
  // has no arrow to be walked. Driving it off the arrows would quietly leave
  // every switch on the page out of the comparison.
  env.byName.ligatures.checked = false;
  env.listeners.input({ target: env.byName.ligatures });
  env.compare.fire();
  check("a checkbox off the factory is put back by untuned",
        env.byName.ligatures.checked === true,
        String(env.byName.ligatures.checked));
  env.compare.fire();
  check("and comes back to where you left it",
        env.byName.ligatures.checked === false,
        String(env.byName.ligatures.checked));
}

// 33. Knobs the font cannot answer. A face with no ligature rules and no pnum
//     draws the identical page whichever way those two are set, so the rows
//     are greyed rather than left inviting an experiment with no result.
{
  const env = await loaded(fakeStorage());
  const {ligatures, figures} = env.byName;
  check("a family without the features has both knobs out of reach",
        ligatures.disabled === true && figures.disabled === true,
        `${ligatures.disabled} ${figures.disabled}`);
  check("each saying which feature is missing",
        /ligature rules/.test(ligatures.title) && /proportional/.test(figures.title),
        ligatures.title + " | " + figures.title);

  env.family.choose("Sample");
  check("a family that has them gets them back",
        ligatures.disabled === false && figures.disabled === false,
        `${ligatures.disabled} ${figures.disabled}`);
  check("with nothing left to explain",
        ligatures.title === "" && figures.title === "",
        ligatures.title + " | " + figures.title);

  // Greyed is about the font, not about the value: a reset puts every knob
  // back to what the config says and cannot make a face grow a feature.
  env.family.choose("Alto");
  env.clicks.font();
  check("and a reset does not hand back a knob the font cannot answer",
        ligatures.disabled === true, String(ligatures.disabled));
}

// 34. Stem darkening, which the font decides only half of. FreeType darkens in
//     the CF2 interpreter, on a scaled load, and in the auto-hinter, at a light
//     target, so the hinting row two above settles it as much as the face does
//     -- and the row has to follow that knob, not just the family.
{
  const env = await loaded(fakeStorage());
  const {stem_darkening: darkening, hinting} = env.byName;
  check("the hinting row is listened to, since the rule reads it",
        typeof hinting.on.change === "function");
  check("a TrueType family under normal hinting cannot be darkened",
        darkening.disabled === true, String(darkening.disabled));
  check("and the row says which half is missing",
        /TrueType outlines/.test(darkening.title), darkening.title);

  hinting.value = "light";
  hinting.on.change();
  check("light hinting hands it back, with no family change at all",
        darkening.disabled === false && darkening.title === "",
        `${darkening.disabled} ${darkening.title}`);

  hinting.value = "auto";
  hinting.on.change();
  check("the auto-hinter takes it away again",
        darkening.disabled === true, String(darkening.disabled));
  check("for a reason of its own, not the one the outlines gave",
        /auto hinting/.test(darkening.title) &&
          !/TrueType/.test(darkening.title), darkening.title);

  // A CFF family is darkened under everything but auto. Switching to one
  // brings its own hinting with it, so the row is worked out again from both:
  // Sample's config says normal, which for CFF outlines is enough.
  env.family.choose("Sample");
  check("a CFF family is darkened under the hinting its config asks for",
        darkening.disabled === false, String(darkening.disabled));
  hinting.value = "auto";
  hinting.on.change();
  check("and the auto-hinter still takes it away, whatever the outlines",
        darkening.disabled === true, String(darkening.disabled));

  // Nothing about the font changed, so a reset must not hand it back: it puts
  // hinting where the config had it, which is what the row follows.
  env.family.choose("Alto");
  hinting.value = "light";
  hinting.on.change();
  check("light hinting on a TrueType family leaves it reachable",
        darkening.disabled === false, String(darkening.disabled));
  env.clicks.font();
  check("and a reset back to normal hinting takes it away",
        darkening.disabled === true, String(darkening.disabled));

  // The compare arrow moves hinting with no event for a listener to hear, so
  // the row has to be worked out from the setter as well.
  hinting.value = "light";
  hinting.on.change();
  const arrow = env.revertList.find(r => r.dataset.reset === "hinting");
  arrow.click();
  check("setting hinting aside for a comparison takes the switch with it",
        darkening.disabled === true, String(darkening.disabled));
  arrow.click();
  check("and putting it back hands the switch back too",
        darkening.disabled === false, String(darkening.disabled));
}

// 35. Grayscale hinting, which three separate facts can take away: the
//     outlines, whether the face carries bytecode at all, and the hinting mode.
{
  const env = await loaded(fakeStorage());
  const {grayscale_hinting: grayscale, hinting} = env.byName;

  // Alto is TrueType and hinted, which is the one combination that reaches it.
  env.family.choose("Alto");
  check("a hinted TrueType family under normal hinting can turn it on",
        grayscale.disabled === false, String(grayscale.disabled));

  for (const mode of ["light", "auto"]) {
    hinting.value = mode;
    hinting.on.change();
    check(`the auto-hinter draws it under ${mode}, so the row goes`,
          grayscale.disabled === true &&
            /auto-hinter/.test(grayscale.title), grayscale.title);
  }
  hinting.value = "none";
  hinting.on.change();
  check("and with no hinting at all there is no interpreter to pick",
        grayscale.disabled === true && /hinting is none/.test(grayscale.title),
        grayscale.title);
  hinting.value = "normal";
  hinting.on.change();
  check("back at normal hinting the row returns",
        grayscale.disabled === false, String(grayscale.disabled));

  // The other two facts are the font's, and switching family brings them.
  env.family.choose("Sample");
  check("a CFF family has no bytecode for either interpreter",
        grayscale.disabled === true &&
          /not TrueType outlines/.test(grayscale.title), grayscale.title);
  env.family.choose("Vari");
  check("and neither has a TrueType family that carries none",
        grayscale.disabled === true &&
          /no hinting bytecode/.test(grayscale.title), grayscale.title);

  // Tricky fonts are FreeType's own exception: they never reach the
  // auto-hinter, so their bytecode runs under light and auto as well. No
  // fixture family is tricky, so the rule itself is asked directly.
  const {grayscaleReason} = env.modules.get("dom.js");
  check("a tricky face keeps the row under light hinting",
        grayscaleReason("truetype", true, true, "light") === "");
  check("and under auto",
        grayscaleReason("truetype", true, true, "auto") === "");
  check("but not when nothing is hinted",
        grayscaleReason("truetype", true, true, "none") !== "");
  check("a non-tricky face loses it under light",
        grayscaleReason("truetype", true, false, "light") !== "");
  check("a family whose faces disagree on format is judged on its bytecode",
        grayscaleReason("mixed", true, false, "normal") === "");
}

// 36. Mono rasterizing leaves a pixel empty or full, so the two knobs that
//     shape coverage in between have nothing left to shape.
{
  const env = await loaded(fakeStorage());
  const {mono, gamma, thresholds} = env.byName;
  check("the coverage knobs start reachable",
        gamma.disabled === false && thresholds.disabled === false,
        `${gamma.disabled}/${thresholds.disabled}`);

  mono.checked = true;
  mono.on.change();
  check("turning mono on takes gamma away",
        gamma.disabled === true && /empty or full/.test(gamma.title), gamma.title);
  check("and the thresholds with it",
        thresholds.disabled === true, String(thresholds.disabled));
  check("and the steppers beside gamma, which are a second way in",
        env.stepList.filter(s => s.dataset.for === "gamma")
          .every(s => s.disabled === true));

  mono.checked = false;
  mono.on.change();
  check("turning it off hands both back",
        gamma.disabled === false && thresholds.disabled === false,
        `${gamma.disabled}/${thresholds.disabled}`);

  // A reset moves the switch with no event for a listener to hear, so the two
  // rows have to be worked out from there as well.
  mono.checked = true;
  mono.on.change();
  env.clicks.font();
  await settle();
  check("a reset turns mono off and hands the coverage knobs back",
        mono.checked === false && gamma.disabled === false,
        `${mono.checked}/${gamma.disabled}`);
}

// 57c. Setting a language aside for a comparison is not choosing one. The
//      arrow moves the row through the same setter a person does, so without
//      care the peeked value is written down as the one your text is in, and
//      a trip through a preset brings back whatever you were comparing with.
{
  const storage = fakeStorage({ "crossglyph.text": "eigener Text",
                                "crossglyph.sample": "" });
  const env = await loaded(storage, DEFAULTS, { languages: ["en"] });
  env.byName.language.value = "de";
  env.listeners.input({ target: env.byName.language });
  check("the language your text is in is written down",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);

  const arrow = env.revertList.find(r => r.dataset.reset === "language");
  arrow.click();
  check("setting it aside does not rewrite that",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);
  arrow.click();
  check("and neither does putting it back",
        storage.data["crossglyph.language"] === "de",
        storage.data["crossglyph.language"]);
}

// 35a. A file the app was started on is no family and reports none of the
//      facts a family reports. A knob is greyed on an answer, never on the
//      absence of one: the file may well carry bytecode, and nothing has
//      looked.
{
  const bare = { ...DEFAULTS, family: "", font: "Loose.ttf",
                 faces: ["regular"], families: [] };
  const env = await loaded(fakeStorage(), bare);
  check("the bare file is what the picker is on",
        env.family.value === "", env.family.value);
  check("and grayscale hinting is not greyed on facts nobody gave",
        env.byName.grayscale_hinting.disabled === false,
        env.byName.grayscale_hinting.title);
}

// 58. What this install is, in the island under the specimen: the version, the
//     renderer it carries, and the state of the asking. The commit is there
//     because two installs on one version can carry different renderers.
{
  const env = await loaded(fakeStorage());
  check("the island names the product and version",
        env.about.number.textContent === "1.2.3",
        env.about.number.textContent);
  check("and the name beside it links the project, from the server rather "
        + "than from the markup",
        env.about.home.href === "https://github.com/CrazyCoder/crossglyph",
        env.about.home.href);
  check("and the renderer's commit, shortened the way the CLI does",
        env.about.detail.textContent.includes("45caec3e76c2"),
        env.about.detail.textContent);
  check("a release on the newest version is not told how to update, having "
        + "nothing to update to",
        env.about.detail.textContent.endsWith("45caec3e76c2."),
        env.about.detail.textContent);
  check("the line answers the question the button asks, and says when it "
        + "found out, which is one subject rather than two",
        /^Up to date, checked .* ago\.$/.test(env.about.state.textContent),
        env.about.state.textContent);
  check("and the line below is only what this install is, with nothing "
        + "about updates run into it",
        env.about.detail.textContent === "Render core built from "
        + "crosspoint-reader 45caec3e76c2.",
        env.about.detail.textContent);
  check("and the one press on offer is asking again",
        env.about.button.hidden === false && env.about.update.hidden === true,
        `check ${env.about.button.hidden}, update ${env.about.update.hidden}`);
  check("the whole of it is in the title, where the compact line is not",
        env.about.island.title.includes("crosspoint-reader 45caec3e76c2"),
        env.about.island.title);
}

// 58a. A newer release takes the place of the line about when the asking last
//      happened. It is the only answer worth having while there is one, and
//      one thing on the right is what keeps the island to a single line.
//      The server sends no instruction for a kind this page can install for
//      itself, so the line below stays what this install is.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    available: "2.0.0", latest: "2.0.0", notice: "" } });
  check("the state names the version to move to",
        env.about.state.textContent === "2.0.0 is available.",
        env.about.state.textContent);
  check("and the press on offer is the one that installs it",
        env.about.update.hidden === false && env.about.button.hidden === true,
        `check ${env.about.button.hidden}, update ${env.about.update.hidden}`);
  check("and nothing beside the button tells you to run the command it runs",
        !env.about.detail.textContent.includes("crossglyph update"),
        env.about.detail.textContent);
}

// 58b. A kind that cannot replace its own files says so instead, because the
//      way out differs and the notice is the only place it is said.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    firmware: null, kind: "container", can_self_update: false,
    available: "2.0.0", notice: "Pull the new image to update." },
  });
  check("the notice takes the place of the commit, and stays last, being "
        + "the one sentence with something to do in it",
        env.about.detail.textContent.endsWith("Pull the new image to update."),
        env.about.detail.textContent);
  check("and a core with no stamp is left unsaid rather than guessed",
        !env.about.detail.textContent.includes("crosspoint-reader"),
        env.about.detail.textContent);
  check("and no button offers what this install cannot do",
        env.about.update.hidden === true, String(env.about.update.hidden));
}

// 58c. Checking turned off is said, rather than the line reading as though
//      the answer were merely old.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { about: { checking_off: true } });
  check("the line says the checks are off",
        env.about.state.textContent === "Update checks are off.",
        env.about.state.textContent);
}

// 58d. A check nobody could complete says so. This is the state an automatic
//      check swallows and a manual one must not: a button that goes quiet
//      reads as broken, which is the one thing it cannot do.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { about: { error: "no route", checked_at: null } });
  check("the line says it could not ask",
        env.about.state.textContent === "Could not reach the update server.",
        env.about.state.textContent);
}

// 58e. One of anything is not "1 minutes". This line is on the page every
//      time it loads, and it spends a whole minute of every hour being wrong.
{
  const at = seconds => ({ about: { checked_at: Date.now() / 1000 - seconds } });
  const one = await loaded(fakeStorage(), DEFAULTS, at(90));
  check("one of a unit is said in the singular",
        one.about.state.textContent === "Up to date, checked 1 minute ago.",
        one.about.state.textContent);
  const several = await loaded(fakeStorage(), DEFAULTS, at(2 * 3600));
  check("and more than one is not",
        several.about.state.textContent === "Up to date, checked 2 hours ago.",
        several.about.state.textContent);
}

// 58e. The button asks, and says so while it is asking.
{
  const env = await loaded(fakeStorage());
  const before = env.fetches.checks;
  env.about.press();
  await settle();
  check("it asked", env.fetches.checks === before + 1,
        `${before} -> ${env.fetches.checks}`);
  check("it said so while it was asking",
        env.about.state.steps.includes("Checking..."),
        JSON.stringify(env.about.state.steps));
  check("and it went out and came back rather than staying out",
        JSON.stringify(env.about.button.states) === "[true,false]",
        JSON.stringify(env.about.button.states));
}

// 58f. An answer that never comes still ends the sentence. Without this the
//      line sits on "Checking..." and the button looks stuck.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { checkThrows: true });
  env.about.press();
  await settle();
  check("a failed press says what happened",
        env.about.state.textContent === "Could not reach the update server.",
        env.about.state.textContent);
  check("and the button comes back",
        env.about.button.disabled === false,
        String(env.about.button.disabled));
}

// 58g. What the press learns changes what is on offer, not merely the line it
//      was pressed from: an install that has just heard about a release has to
//      offer the button that installs it.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { checked: { available: "2.0.0" } });
  check("nothing to install before", env.about.update.hidden === true);
  env.about.press();
  await settle();
  check("and the offer after", env.about.update.hidden === false,
        String(env.about.update.hidden));
  check("with the asking button out of the way, one press at a time",
        env.about.button.hidden === true, String(env.about.button.hidden));
}

// 58h. Pressing Update installs, counting its way there on the panel's own
//      bar. It is a megabyte and a half, and a button that says nothing for
//      the whole of it is indistinguishable from one that did nothing.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    available: "2.0.0", latest: "2.0.0",
    notice: "Run crossglyph update to install it." } });
  env.about.apply();
  await settle();
  check("it asked the server to install", env.fetches.applies === 1,
        String(env.fetches.applies));
  check("the bar filled on the way", env.about.fill.widths.includes("50%"),
        JSON.stringify(env.about.fill.widths));
  check("and is gone at the end", env.about.progress.hidden === true,
        String(env.about.progress.hidden));
  check("on the island's own bar, not the panel's",
        env.progressWhat.steps.length === 0,
        JSON.stringify(env.progressWhat.steps));
  check("the sentence says what to do next",
        env.about.updated.textContent ===
          "2.0.0 installed. Close CrossGlyph and open it again to use the update.",
        env.about.updated.textContent);
  check("the line beside the version says it landed",
        env.about.state.textContent === "2.0.0 installed.",
        env.about.state.textContent);
  check("and there is nothing left to press: what is installed is not what "
        + "is running until the tool is started again",
        env.about.update.hidden === true && env.about.button.hidden === true,
        `update ${env.about.update.hidden}, check ${env.about.button.hidden}`);
  check("the button went out and came back",
        JSON.stringify(env.about.update.states) === "[true,false]",
        JSON.stringify(env.about.update.states));
  check("a server that cannot hand itself off does not promise a reload",
        env.reloads() === 0, String(env.reloads()));
}

// 58h1. A local running preview can hand the update to the installed version.
//        The port disappears between processes, so polling tolerates a failed
//        request and reloads only after that version answers.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [
      { event: "done", version: "2.0.0", converting: false, kept: [],
        staged: [], where: "versions/2.0.0", restarting: true,
        restart_log: "D:\\CrossGlyph\\preview.log" },
    ],
    restartAnswers: [
      new TypeError("Failed to fetch"),
      { ...ABOUT, version: "2.0.0", installed: "2.0.0" },
    ],
  });

  await env.about.apply();

  check("the page says the automatic restart is in progress",
        env.about.updated.textContent ===
          "2.0.0 installed. Restarting CrossGlyph...",
        env.about.updated.textContent);
  check("the vanished server is tried again",
        env.fetches.updateReads === 3, String(env.fetches.updateReads));
  check("the new version causes exactly one reload",
        env.reloads() === 1, String(env.reloads()));
}

// 58h1a. Bootstrap time is not server startup time. As long as the old
//         process says the handoff child is alive, no fixed count turns that
//         truthful answer into a failure.
{
  const starting = Array.from(
    {length: 260}, () => ({ ...ABOUT, handoff: "starting" }));
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [
      { event: "done", version: "2.0.0", converting: false, kept: [],
        staged: [], where: "versions/2.0.0", restarting: true,
        restart_log: "D:\\CrossGlyph\\preview.log" },
    ],
    restartAnswers: [
      ...starting,
      { ...ABOUT, version: "2.0.0", installed: "2.0.0" },
    ],
  });

  await env.about.apply();

  check("a long live bootstrap still reaches the new version",
        env.reloads() === 1, String(env.reloads()));
  check("the bootstrap outlived the former overall retry count",
        env.fetches.updateReads > 240, String(env.fetches.updateReads));
}

// 58h1b. A child that exits while the old server still answers has failed.
//         The log is the evidence left by the hidden process.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [
      { event: "done", version: "2.0.0", converting: false, kept: [],
        staged: [], where: "versions/2.0.0", restarting: true,
        restart_log: "D:\\CrossGlyph\\preview.log" },
    ],
    restartAnswers: [{ ...ABOUT, handoff: "failed" }],
  });

  await env.about.apply();

  check("a failed handoff does not reload",
        env.reloads() === 0, String(env.reloads()));
  check("a failed handoff names the restart log",
        env.about.updated.textContent.endsWith(
          "See D:\\CrossGlyph\\preview.log."),
        env.about.updated.textContent);
}

// 58h1c. Once the old server disappears, the new server gets a bounded
//         startup window. Silence through all of it is a real manual fallback.
{
  const unavailable = Array.from(
    {length: 240}, () => new TypeError("Failed to fetch"));
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [
      { event: "done", version: "2.0.0", converting: false, kept: [],
        staged: [], where: "versions/2.0.0", restarting: true,
        restart_log: "D:\\CrossGlyph\\preview.log" },
    ],
    restartAnswers: unavailable,
  });

  await env.about.apply();

  check("an absent replacement does not reload",
        env.reloads() === 0, String(env.reloads()));
  check("an absent replacement receives manual guidance",
        env.about.updated.textContent.includes(
          "Close CrossGlyph and open it again"),
        env.about.updated.textContent);
}


// 58h2. A reload is told as much, and so is a second browser. What a restart
//       would run is read off the disk by the server, so the answer does not
//       live in the page that pressed the button -- and an update done from
//       the command line, while this page sat open, reaches it too.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    pending: "2.0.0", available: "2.0.0", latest: "2.0.0" } });
  check("a page that installed nothing still says what is waiting",
        env.about.state.textContent === "2.0.0 installed.",
        env.about.state.textContent);
  check("and offers nothing to install",
        env.about.update.hidden === true && env.about.button.hidden === true,
        `update ${env.about.update.hidden}, check ${env.about.button.hidden}`);
}

// 58h3. And a check afterwards does not offer it again. This process is still
//       the old version, so the manifest goes on looking newer to it for as
//       long as it runs -- the page is the only thing that knows the release
//       is already on the disk.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    available: "2.0.0", latest: "2.0.0" } });
  env.about.apply();
  await settle();
  const {showAbout} = env.modules.get("about.js");

  showAbout({ ...ABOUT, available: "2.0.0", latest: "2.0.0" });
  check("the answer that would have offered it says it is installed",
        env.about.state.textContent === "2.0.0 installed.",
        env.about.state.textContent);
  check("and offers nothing", env.about.update.hidden === true,
        String(env.about.update.hidden));
}

// 58h2. The release a rollback turned down. A page load says nothing about
//       it, because that is the tool raising the subject; the button asks on
//       somebody's behalf, and the answer says why it had gone unmentioned.
//       Offering it again with no explanation would read as the button being
//       broken rather than as a rule being followed.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    available: null, latest: "2.0.0", turned_down: false } });
  check("a load offers nothing", env.about.update.hidden === true,
        String(env.about.update.hidden));

  const {showAbout} = env.modules.get("about.js");
  showAbout({ ...ABOUT, available: "2.0.0", latest: "2.0.0",
              turned_down: true });
  check("what the button found is offered",
        env.about.update.hidden === false, String(env.about.update.hidden));
  check("and the island says why it had said nothing",
        env.about.detail.textContent.includes("rolled back from 2.0.0"),
        env.about.detail.textContent);
}

// 58i0. A launcher an update could not replace is left beside the live one,
//       and the sentence is where anybody learns it will be applied at the
//       next launch rather than now.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [{ event: "done", version: "2.0.0", converting: false,
                    kept: [], staged: ["crossglyph.cmd"],
                    where: "versions/2.0.0" }] });
  env.about.apply();
  await settle();
  check("the staged launcher is named",
        env.about.updated.textContent.includes("crossglyph.cmd"),
        env.about.updated.textContent);
  check("and when it lands",
        env.about.updated.textContent.includes("next launch"),
        env.about.updated.textContent);
}

// 58i. A file the user had edited is kept, and saying so is the only way
//      anybody learns the .new is there.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [{ event: "done", version: "2.0.0", converting: false, staged: [],
                    kept: ["fonts/conf/all.conf", "compose.build.yaml",
                           "compose.yaml"], where: "versions/2.0.0" }] });
  env.about.apply();
  await settle();
  check("the file it kept is named",
        env.about.updated.textContent.includes("fonts/conf/all.conf"),
        env.about.updated.textContent);
  check("and so is what was written beside it",
        env.about.updated.textContent.includes("all.conf.new"),
        env.about.updated.textContent);
  check("and the managed root file it kept is named",
        env.about.updated.textContent.includes("compose.yaml"),
        env.about.updated.textContent);
  check("with its replacement beside it",
        env.about.updated.textContent.includes("compose.yaml.new"),
        env.about.updated.textContent);
  check("the local build override it kept is named",
        env.about.updated.textContent.includes("compose.build.yaml"),
        env.about.updated.textContent);
  check("with its replacement beside it too",
        env.about.updated.textContent.includes("compose.build.yaml.new"),
        env.about.updated.textContent);
}

// 58j. A refusal arrives as a step rather than a status, because what the
//      page has to show is the sentence.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" },
    updateSteps: [{ event: "error", error: "the download does not match the "
                                           + "hash the manifest gave" }] });
  env.about.apply();
  await settle();
  check("the refusal is on the page",
        env.about.updated.textContent.includes("does not match"),
        env.about.updated.textContent);
  check("and the offer stays, since nothing was installed",
        env.about.update.hidden === false, String(env.about.update.hidden));
}

// 58k. An answer that never comes still ends the run. Without this the bar
//      sits part full and the button stays out, which reads as an update
//      still going.
{
  const env = await loaded(fakeStorage(), DEFAULTS, {
    about: { available: "2.0.0", latest: "2.0.0" }, applyFails: true });
  env.about.apply();
  await settle();
  check("the bar is gone", env.about.progress.hidden === true,
        String(env.about.progress.hidden));
  check("the button comes back", env.about.update.disabled === false,
        String(env.about.update.disabled));
  check("and the failure is said rather than swallowed",
        env.about.updated.textContent.includes("connection lost"),
        env.about.updated.textContent);
}

// 59. The panel tabs. Below the width where all three columns fit, the export
//     panel folds in beside the knobs and one of them is on screen at a time.
//     Which one is an attribute on the root, and only the stylesheet reads it:
//     whether there is anything to switch at all is a width, so nothing here
//     measures a window or listens for a resize.
{
  const env = await loaded(fakeStorage());
  check("nothing is said before a press, so the page opens on the knobs "
        + "without waiting for a script",
        env.root.dataset.panel === undefined,
        String(env.root.dataset.panel));

  env.tabs.press("export");
  check("a press says which panel", env.root.dataset.panel === "export",
        env.root.dataset.panel);
  check("and the tabs say which of them it was",
        env.tabs.export.attrs["aria-pressed"] === "true"
        && env.tabs.tune.attrs["aria-pressed"] === "false",
        JSON.stringify([env.tabs.tune.attrs, env.tabs.export.attrs]));

  env.tabs.press("tune");
  check("and back", env.root.dataset.panel === "tune", env.root.dataset.panel);
  check("with the pressed state following",
        env.tabs.tune.attrs["aria-pressed"] === "true"
        && env.tabs.export.attrs["aria-pressed"] === "false",
        JSON.stringify([env.tabs.tune.attrs, env.tabs.export.attrs]));
}

// 59a. A build marks the tab it is running behind. It is minutes long and it
//      reports into a panel that may not be the one on screen, so without the
//      mark a reader who went back to the knobs is told nothing at all.
{
  const env = await loaded(fakeStorage());
  check("the tab is unmarked before", env.tabs.busy.hidden === true);
  await env.builds.one();
  // The press is awaited, so the run is over by here: the mark outlasting it
  // is the point of the mark. What it says is that something happened in
  // there, and that is as true a minute later as it is while it is happening.
  check("a build marks it, and the mark outlasts the run",
        env.tabs.busy.hidden === false, String(env.tabs.busy.hidden));

  env.tabs.press("export");
  check("looking clears it", env.tabs.busy.hidden === true,
        String(env.tabs.busy.hidden));
}

// 59a2. The other mark a tab carries: work in the panel behind it that the
//       .conf has not got. Save stands under the knobs alone, so from the
//       export tab there is no lit button to say the export settings have been
//       edited, and from the knobs tab those settings were never on screen.
//       Each mark is that sentence about the panel you are not looking at.
{
  const env = await loaded(fakeStorage());
  check("both tabs open clean",
        env.tabs.tuneUnsaved.hidden === true &&
        env.tabs.exportUnsaved.hidden === true,
        JSON.stringify([env.tabs.tuneUnsaved.hidden,
                        env.tabs.exportUnsaved.hidden]));

  // The page opens on the knobs, so this is an edit to the panel behind the
  // other tab -- which is exactly the case the mark exists for.
  const wasSize1 = env.exportForm.elements.size1.value;
  env.exportForm.elements.size1.value = "10";
  env.exportForm.edit("size1");
  check("an export edit marks the tab it is behind",
        env.tabs.exportUnsaved.hidden === false,
        String(env.tabs.exportUnsaved.hidden));
  check("and the knobs, which are the panel on screen, say nothing",
        env.tabs.tuneUnsaved.hidden === true,
        String(env.tabs.tuneUnsaved.hidden));

  env.tabs.press("export");
  check("looking at it takes its mark down",
        env.tabs.exportUnsaved.hidden === true,
        String(env.tabs.exportUnsaved.hidden));

  env.byName.gamma.value = "2";
  env.listeners.input({ target: env.byName.gamma });
  check("a knob edited from the export tab marks the tab it was made on",
        env.tabs.tuneUnsaved.hidden === false,
        String(env.tabs.tuneUnsaved.hidden));
  check("and the tab you are on still says nothing about itself",
        env.tabs.exportUnsaved.hidden === true,
        String(env.tabs.exportUnsaved.hidden));

  // Switching is one of the moments both have to be worked out again: nothing
  // was edited, and which panel each mark is about has changed all the same.
  env.tabs.press("tune");
  check("going back takes the knobs' mark down and puts the export one up",
        env.tabs.tuneUnsaved.hidden === true &&
        env.tabs.exportUnsaved.hidden === false,
        JSON.stringify([env.tabs.tuneUnsaved.hidden,
                        env.tabs.exportUnsaved.hidden]));

  // Compared rather than latched: a value put back is not work, however it got
  // there, which is the same rule Save is lit by.
  env.exportForm.elements.size1.value = wasSize1;
  env.exportForm.edit("size1");
  check("and putting the value back takes it down again",
        env.tabs.exportUnsaved.hidden === true,
        String(env.tabs.exportUnsaved.hidden));
}

// 59b. Leaving the panel the build ran in clears it too. The mark is for a
//      result nobody has seen, and watching it arrive is having seen it.
{
  const env = await loaded(fakeStorage());
  env.tabs.press("export");
  await env.builds.one();
  env.tabs.press("tune");
  check("the mark does not follow you out",
        env.tabs.busy.hidden === true, String(env.tabs.busy.hidden));
}

// 59c. The update's bar has no mark to leave. It draws in the island under the
//      specimen, which nothing hides.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { about: {
    available: "2.0.0", latest: "2.0.0" } });
  env.about.apply();
  await settle();
  check("an update marks no tab", env.tabs.busy.hidden === true,
        String(env.tabs.busy.hidden));
}

// 60. Folded sections open independently and remember that choice. The root
//     attribute and stylesheet do the folding, which lets boot.js restore it
//     before the first paint rather than flashing hidden content on every load.
{
  const storage = fakeStorage();
  const env = await loaded(storage);
  check("all headings say what the root says",
        env.fold.page.attrs["aria-expanded"] === "false" &&
        env.fold.mod.attrs["aria-expanded"] === "false" &&
        env.fold.device.attrs["aria-expanded"] === "false" &&
        env.fold.text.attrs["aria-expanded"] === "false",
        JSON.stringify([env.fold.page.attrs, env.fold.mod.attrs,
                        env.fold.device.attrs, env.fold.text.attrs]));

  env.fold.press("text");
  check("the Text press opens its card", env.root.dataset.folds === "text",
        env.root.dataset.folds);
  check("the Text heading says so where a screen reader hears it",
        env.fold.text.attrs["aria-expanded"] === "true",
        env.fold.text.attrs["aria-expanded"]);
  check("the Text fold is written down",
        storage.data["crossglyph.folds"] === "text",
        storage.data["crossglyph.folds"]);
  env.fold.press("text");

  env.fold.press("page");
  check("a press opens that one", env.root.dataset.folds === "page",
        env.root.dataset.folds);
  check("and says so where a screen reader hears it",
        env.fold.page.attrs["aria-expanded"] === "true",
        env.fold.page.attrs["aria-expanded"]);
  check("and says so in storage", storage.data["crossglyph.folds"] === "page",
        storage.data["crossglyph.folds"]);

  env.fold.press("mod");
  check("the other opens beside it rather than instead of it",
        env.root.dataset.folds === "page mod", env.root.dataset.folds);

  env.fold.press("page");
  check("and closes on its own", env.root.dataset.folds === "mod",
        env.root.dataset.folds);
  check("with that written down too, rather than left to the default",
        storage.data["crossglyph.folds"] === "mod",
        storage.data["crossglyph.folds"]);
}

// The font folder is not only ours to change: a font gets dropped into it and
// a config gets edited beside it, both while the page is open. Reaching the
// folder means leaving the window, so coming back is when the page asks again.
{
  const later = structuredClone(DEFAULTS);
  later.families.push({ name: "Newcomer", faces: ["regular"],
                        files: { regular: "Newcomer.ttf" },
                        tuning: { ...DEFAULTS.families[0].tuning },
                        features: {}, conf: "newcomer.conf" });
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  const named = () => env.family.options.map(o => o.value).join();
  const was = named();

  // Typed into the export panel and not built yet, which is unsaved work of
  // exactly the kind the knobs are.
  env.exportForm.elements.ranges.value = "0x2200-0x22FF";

  env.returning();
  await settle();
  check("coming back to the page asks the folder again",
        env.fetches.defaults === 2, env.fetches.defaults);
  check("a font added while it was away is in the picker",
        named() === was + ",Newcomer", named());
  check("and what was being tuned keeps its place",
        env.family.value === "Alto", env.family.value);
  check("and what was typed beside it is still typed",
        env.exportForm.elements.ranges.value === "0x2200-0x22FF",
        env.exportForm.elements.ranges.value);
}

{
  const env = await loaded(fakeStorage());
  env.sandbox.document.hidden = true;
  env.returning();
  await settle();
  check("a tab in the background asks nothing", env.fetches.defaults === 1,
        env.fetches.defaults);
}

// A folder that has not moved is the case that happens every single time, so
// it has to cost nothing -- and a face swapped under an unchanged config is
// the case that looks like nothing and is not.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { later: DEFAULTS });
  const drawn = env.fetches.render;
  env.returning();
  await settle();
  check("a folder that has not moved is not redrawn",
        env.fetches.render === drawn, env.fetches.render);
}

{
  const later = structuredClone(DEFAULTS);
  // An italic dropped in beside the family, which its config says nothing
  // about: the knobs are untouched and the page is still drawn with two faces.
  later.families.find(one => one.name === "Alto")
       .faces = ["bold", "italic", "regular"];
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  const shown = () => env.badges.children.map(b => b.dataset.loaded).join();
  const drawn = env.fetches.render;
  check("two of the four to start with", shown() === "yes,yes,no,no", shown());

  env.returning();
  await settle();
  check("a face that arrived under an unchanged config lights its badge",
        shown() === "yes,yes,yes,no", shown());
  check("and the page is drawn again, since the one on it has no italic",
        env.fetches.render === drawn + 1, env.fetches.render);
}

// A config edited in an editor, with nothing of yours in the panel to lose.
{
  const later = structuredClone(DEFAULTS);
  later.families.find(one => one.name === "Alto").tuning.gamma = 1.75;
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  check("the knob starts where the file had it",
        env.byName.gamma.value === "1.2", env.byName.gamma.value);

  env.returning();
  await settle();
  check("an untouched panel follows the file", env.byName.gamma.value === "1.75",
        env.byName.gamma.value);
  check("and says nothing about it, since nothing was lost",
        env.note.textContent === "", env.note.textContent);
}

// The same edit, arriving on top of knobs you have not saved. Those are the
// one thing on the page with nowhere else to live, so the file does not win.
{
  const later = structuredClone(DEFAULTS);
  later.families.find(one => one.name === "Alto").tuning.gamma = 1.75;
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  env.byName.gamma.value = "2.5";
  env.listeners.input({ target: env.byName.gamma });

  env.returning();
  await settle();
  check("unsaved knobs survive a config that changed under them",
        env.byName.gamma.value === "2.5", env.byName.gamma.value);
  check("and the page says the file moved",
        env.note.textContent.includes("changed on disk"), env.note.textContent);
  // Asked by pressing it, since the arrow's own words are the same either
  // way: what has to have moved is the value behind it.
  env.revertList.find(r => r.dataset.reset === "gamma").click();
  check("and the arrow now bypasses to the file as it is now, not as it was",
        env.byName.gamma.value === "1.75", env.byName.gamma.value);
}

// A variable family's slot coordinates live in the same config, and a clean
// panel follows those too. Re-rendering with the old picker value would put
// the value from before the edit back on the page.
{
  const later = structuredClone(DEFAULTS);
  later.families.find(one => one.name === "Vari").variable.weights.text = 550;
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  env.family.choose("Vari");
  await settle();
  check("the variable slot starts where the file had it",
        env.byName.axis_text.value === "400", env.byName.axis_text.value);

  env.returning();
  await settle();
  check("an untouched variable slot follows the file",
        env.byName.axis_text.value === "550", env.byName.axis_text.value);
  check("and the next page is drawn at the new coordinate",
        env.fetches.bodies.at(-1).axes.text === 550,
        JSON.stringify(env.fetches.bodies.at(-1).axes));
}

// A coordinate already moved in the panel is work of yours, just as a tuning
// knob is. The file becomes its new baseline without taking that work away.
{
  const later = structuredClone(DEFAULTS);
  later.families.find(one => one.name === "Vari").variable.weights.text = 550;
  const env = await loaded(fakeStorage(), DEFAULTS, { later });
  env.family.choose("Vari");
  await settle();
  env.byName.axis_text.value = "900";
  env.byName.axis_text.on.change();
  await settle();

  env.returning();
  await settle();
  check("an unsaved variable slot survives the file changing",
        env.byName.axis_text.value === "900", env.byName.axis_text.value);
  check("and the page keeps drawing what the panel says",
        env.fetches.bodies.at(-1).axes.text === 900,
        JSON.stringify(env.fetches.bodies.at(-1).axes));
}

// Frame color follows the page until the picker records a choice of its own.
// Saving another device setting must not turn the derived color into a choice.
{
  const storage = fakeStorage();
  const env = await loaded(storage);
  const device = env.modules.get("device.js");
  check("a light page starts with the white reader frame",
        env.device.color.value === "white", env.device.color.value);

  env.device.frame.checked = false;
  env.device.edit(env.device.frame);
  check("saving another device setting leaves frame color automatic",
        !("color" in JSON.parse(storage.data["crossglyph.device"])),
        storage.data["crossglyph.device"]);

  env.root.classList.toggle("dark", true);
  device.syncDeviceColor();
  check("automatic frame color follows the dark page",
        env.device.color.value === "black", env.device.color.value);

  env.device.color.value = "white";
  env.device.change(env.device.color);
  check("a chosen frame color is remembered",
        JSON.parse(storage.data["crossglyph.device"]).color === "white",
        storage.data["crossglyph.device"]);
  device.syncDeviceColor();
  check("a chosen frame color can differ from the page",
        env.device.color.value === "white", env.device.color.value);
}

// The browser's measured grid decides when the preview moves under Tune.
// DPR, frame and scale all change that width after CSS breakpoints are known.
{
  const env = await loaded(fakeStorage(), undefined, {
    viewportWidth: 1274, twoColumnWidth: 1030,
  });
  check("a compact preview stays beside Tune while both columns fit",
        env.root.dataset.previewColumns === "two",
        env.root.dataset.previewColumns);

  env.resize(1100, 1280);
  check("an overflowing preview moves under Tune",
        env.root.dataset.previewColumns === "one",
        env.root.dataset.previewColumns);

  env.resize(1274, 1030, 1259);
  check("a compact preview returns beside Tune after resizing",
        env.root.dataset.previewColumns === "two",
        env.root.dataset.previewColumns);
}

// A model chosen through the select must survive a fresh page load, not only
// write a value that no later page is known to consume.
{
  const storage = fakeStorage();
  const first = await loaded(storage);
  first.device.model.value = "x3";
  first.device.change(first.device.model);
  await settle();
  check("the chosen reader model is saved",
        JSON.parse(storage.data["crossglyph.device"]).device === "x3",
        storage.data["crossglyph.device"]);

  const reloaded = await loaded(storage);
  check("the chosen reader model survives a page reload",
        reloaded.device.model.value === "x3", reloaded.device.model.value);
  check("the reloaded page draws with the chosen reader model",
        reloaded.fetches.bodies.at(-1).page.device === "x3",
        JSON.stringify(reloaded.fetches.bodies.at(-1).page));
}

// The device panel owns presentation settings, while its model also changes
// the render core's native page geometry.
{
  const storage = fakeStorage({"crossglyph.device": JSON.stringify({
    device: "x3", color: "white", frame: false, scale: "custom",
    paper: "100", ink: "50", calibration: "110",
  })});
  const env = await loaded(storage, undefined, {renderOk: true});
  check("the saved reader model reaches the render request",
        env.fetches.bodies.at(-1).page.device === "x3",
        JSON.stringify(env.fetches.bodies.at(-1).page));
  check("device appearance comes back with the reader model",
        env.device.color.value === "white" && !env.device.frame.checked &&
        env.device.scale.value === "custom");
  check("custom scale keeps its controls visible",
        !env.device.calibrationBox.hidden);
  check("tone controls use the shared 50 to 100 percent range",
        env.device.paper.min === "50" && env.device.paper.max === "100" &&
        env.device.ink.min === "50" && env.device.ink.max === "100");
  check("custom scale covers 50 to 150 percent",
        env.device.calibration.min === "50" &&
        env.device.calibration.max === "150");
  check("loaded numeric controls and sliders agree",
        env.device.paper.value === "100" &&
        env.device.paperSlider.value === "100" &&
        env.device.ink.value === "50" &&
        env.device.inkSlider.value === "50" &&
        env.device.calibration.value === "110" &&
        env.device.calibrationSlider.value === "110");

  const customHeight = parseFloat(env.device.surface.style.height);
  env.device.scale.value = "device";
  env.device.change(env.device.scale);
  const deviceHeight = parseFloat(env.device.surface.style.height);
  check("device size is fixed while custom applies its percentage",
        Math.abs(customHeight / deviceHeight - 1.1) < 1e-9,
        `${customHeight} / ${deviceHeight}`);
  check("only custom scale shows the calibration controls",
        env.device.calibrationBox.hidden);
  env.device.scale.value = "custom";
  env.device.change(env.device.scale);

  env.modules.get("device.js").paintDevicePage();
  const lighterInk = env.device.canvas.pixels[0];
  env.device.inkSlider.value = "100";
  env.device.inkSlider.fire();
  check("the shared slider updates the numeric field",
        env.device.ink.value === "100", env.device.ink.value);
  check("more ink makes the black plane darker",
        env.device.canvas.pixels[0] < lighterInk,
        `${env.device.canvas.pixels[0]} is not darker than ${lighterInk}`);
  check("the shared slider saves the device value",
        JSON.parse(storage.data["crossglyph.device"]).ink === "100",
        storage.data["crossglyph.device"]);

  env.device.paper.value = "50";
  env.device.edit(env.device.paper);
  env.device.step(env.device.paper, -1);
  check("the paper stepper stops at 50 percent",
        env.device.paper.value === "50" &&
        env.device.paperSlider.value === "50");
  env.device.step(env.device.calibration, 1, true);
  check("the custom stepper takes the five percent it declares",
        env.device.calibration.value === "115" &&
        env.device.calibrationSlider.value === "115",
        env.device.calibration.value);
  check("the custom stepper updates the ruler to its calibrated length",
        Math.abs(parseFloat(env.device.ruler.style.width)
          - 100 * 96 / 25.4 * 1.15) < .001,
        env.device.ruler.style.width);

  env.device.model.value = "x4";
  env.device.change(env.device.model);
  await settle();
  check("changing reader redraws with its native geometry",
        env.fetches.bodies.at(-1).page.device === "x4",
        JSON.stringify(env.fetches.bodies.at(-1).page));

  env.device.reset();
  await settle();
  check("reset device preview restores its declared defaults",
        env.device.model.value === "x4" &&
        env.device.color.value === "white" &&
        env.device.frame.checked &&
        env.device.scale.value === "pixels" &&
        env.device.calibrationBox.hidden &&
        env.device.paper.value === "90" && env.device.ink.value === "90" &&
        env.device.calibration.value === "100" &&
        env.device.warm.value === "3" && env.device.tint.value === "2.5");
  check("reset keeps numeric fields and sliders together",
        env.device.paperSlider.value === "90" &&
        env.device.inkSlider.value === "90" &&
        env.device.calibrationSlider.value === "100" &&
        env.device.warmSlider.value === "3" &&
        env.device.tintSlider.value === "2.5");
  // The endpoints carry the tint measured off the device: red above blue with
  // green highest, a warm greenish white rather than the cool one this used to
  // assert. fb2xt's frame renderer applies the same constant to the frames.
  check("default screen tones follow the 90 percent endpoints",
        env.device.canvas.pixels.slice(0, 3).join() === "27,28,24" &&
        env.device.canvas.pixels.slice(-4, -1).join() === "231,232,228",
        env.device.canvas.pixels.join());
  check("reset device preview removes its saved state",
        !("crossglyph.device" in storage.data));
}

// The warm and tint knobs. They span the cast's chromatic plane and nothing
// else, so the pair they ship at has to land on the constant the frames were
// rendered with, and zero on both has to be a true neutral.
{
  const storage = fakeStorage();
  const env = await loaded(storage, undefined, {renderOk: true});
  await settle();
  // Shipped is the calibrated frame itself: no filter over the image at all,
  // which is the only way the default stays the pixels the render produced.
  check("the shipped cast leaves the frame image unfiltered",
        env.device.frameImage.style.filter === "",
        String(env.device.frameImage.style.filter));

  env.device.warm.value = "0";
  env.device.edit(env.device.warm);
  env.device.tint.value = "0";
  env.device.edit(env.device.tint);
  await settle();
  // 90 percent paper is level 230, and neutral makes that #e6e6e6 exactly --
  // the interface's own --stage grey, which is the point of being able to
  // reach zero. Ink 90 is level 26.
  check("zero on both knobs paints a neutral grey page",
        env.device.canvas.pixels.slice(0, 3).join() === "26,26,26" &&
        env.device.canvas.pixels.slice(-4, -1).join() === "230,230,230",
        env.device.canvas.pixels.join());
  check("and hands the frame the difference from what it was baked with",
        env.device.frameImage.style.filter === "url(#frame-tint)" &&
        // -(2/3, 5/3, -7/3) over 255: red down a little, green more, blue up.
        Math.abs(Number(env.device.tintFuncs["frame-tint-r"].attrs.intercept) +
                 2 / 3 / 255) < 1e-12 &&
        Math.abs(Number(env.device.tintFuncs["frame-tint-g"].attrs.intercept) +
                 5 / 3 / 255) < 1e-12 &&
        Math.abs(Number(env.device.tintFuncs["frame-tint-b"].attrs.intercept) -
                 7 / 3 / 255) < 1e-12,
        JSON.stringify([env.device.frameImage.style.filter,
                        env.device.tintFuncs["frame-tint-r"].attrs,
                        env.device.tintFuncs["frame-tint-g"].attrs,
                        env.device.tintFuncs["frame-tint-b"].attrs]));

  // Warm is the red-blue separation and moves nothing else: green sits where
  // tint alone puts it, whatever warm is doing.
  env.device.warm.value = "12";
  env.device.edit(env.device.warm);
  await settle();
  const paper = env.device.canvas.pixels.slice(-4, -1);
  check("warm parts red from blue and leaves green where it was",
        paper[0] === 236 && paper[1] === 230 && paper[2] === 224,
        paper.join());

  check("the knobs are saved with the rest of the device panel",
        JSON.parse(storage.data["crossglyph.device"]).warm === "12" &&
        JSON.parse(storage.data["crossglyph.device"]).tint === "0",
        storage.data["crossglyph.device"]);

  const back = await loaded(storage, undefined, {renderOk: true});
  await settle();
  check("and come back on the next load",
        back.device.warm.value === "12" && back.device.tint.value === "0" &&
        back.device.warmSlider.value === "12" &&
        back.device.tintSlider.value === "0",
        `${back.device.warm.value}/${back.device.tint.value}`);
}

// Per-knob reset. A plain one, unlike the tuning column's arrow: there is no
// config behind these, only the value the markup declares, so there is no
// second value worth holding on to.
{
  const storage = fakeStorage();
  const env = await loaded(storage, undefined, {renderOk: true});
  await settle();
  check("a panel on its defaults offers no arrows",
        Object.values(env.device.resets).every(arrow => arrow.hidden),
        JSON.stringify(Object.fromEntries(
          Object.entries(env.device.resets).map(([k, v]) => [k, v.hidden]))));

  env.device.paper.value = "100";
  env.device.edit(env.device.paper);
  await settle();
  check("a knob off its default offers one, and says what it goes back to",
        env.device.resets["device-paper"].hidden === false &&
        env.device.resets["device-paper"].title === "Reset to 90" &&
        env.device.resets["device-ink"].hidden === true,
        env.device.resets["device-paper"].title);

  env.device.resets["device-paper"].press();
  await settle();
  check("pressing it puts the declared value back",
        env.device.paper.value === "90" &&
        env.device.paperSlider.value === "90" &&
        env.device.resets["device-paper"].hidden === true,
        env.device.paper.value);
  check("and that is a change, so the store has it",
        JSON.parse(storage.data["crossglyph.device"]).paper === "90",
        storage.data["crossglyph.device"]);

  // The cast knobs ship at values a reset has to land on exactly, 2.5 among
  // them: a reset that snapped to whole numbers would leave tint offering an
  // arrow it could never clear.
  env.device.tint.value = "-4";
  env.device.edit(env.device.tint);
  await settle();
  check("a fractional default is offered and reached",
        env.device.resets["device-tint"].title === "Reset to 2.5",
        env.device.resets["device-tint"].title);
  env.device.resets["device-tint"].press();
  await settle();
  check("and the arrow goes once it is back on it",
        env.device.tint.value === "2.5" &&
        env.device.resets["device-tint"].hidden === true,
        env.device.tint.value);

  // The custom scale is a ruler measurement, so its arrow has the ruler to put
  // back as well as the field.
  env.device.scale.value = "custom";
  env.device.change(env.device.scale);
  env.device.calibration.value = "120";
  env.device.edit(env.device.calibration);
  await settle();
  check("the custom scale offers one too",
        env.device.resets["device-calibration-range"].hidden === false &&
        env.device.resets["device-calibration-range"].title === "Reset to 100",
        env.device.resets["device-calibration-range"].title);
  env.device.resets["device-calibration-range"].press();
  await settle();
  check("pressing it takes the ruler back with the field",
        env.device.calibration.value === "100" &&
        env.device.calibrationSlider.value === "100" &&
        Math.abs(parseFloat(env.device.ruler.style.width) - 100 * 96 / 25.4)
          < .001 &&
        env.device.resets["device-calibration-range"].hidden === true,
        `${env.device.calibration.value} ${env.device.ruler.style.width}`);
  env.device.scale.value = "pixels";
  env.device.change(env.device.scale);

  // A value restored from the store is still a value off the default, so the
  // arrow has to be there on the next load rather than only after an edit.
  env.device.warm.value = "-6";
  env.device.edit(env.device.warm);
  await settle();
  const back = await loaded(storage, undefined, {renderOk: true});
  await settle();
  check("a loaded panel offers arrows for what the store carries",
        back.device.warm.value === "-6" &&
        back.device.resets["device-warm"].hidden === false &&
        back.device.resets["device-paper"].hidden === true,
        `${back.device.warm.value} ${back.device.resets["device-warm"].hidden}`);

  back.device.reset();
  await settle();
  check("the panel's own reset clears every arrow with it",
        Object.values(back.device.resets).every(arrow => arrow.hidden),
        JSON.stringify(Object.fromEntries(
          Object.entries(back.device.resets).map(([k, v]) => [k, v.hidden]))));
}

// Every device is rendered twice, and which frame is on screen follows the
// scale. 1:1 takes the one whose aperture is the panel itself, so the frame
// draws at its own pixels; every other scale takes the tall one, which has the
// resolution fit asks for at a high pixel ratio.
{
  const env = await loaded(fakeStorage(), undefined, {renderOk: true});
  await settle();
  check("1:1 takes the frame rendered at the panel's own size",
        env.device.scale.value === "pixels" &&
        env.device.frameImage.src === "device/x4-white-1to1.png",
        `${env.device.scale.value} ${env.device.frameImage.src}`);
  // 612 is that frame's own width: the factor is native over aperture over the
  // pixel ratio, and an aperture already at native makes that one.
  check("and lays it out from that frame's geometry, unscaled",
        env.device.surface.style.width === "612px" &&
        env.device.surface.style.height === "996px",
        `${env.device.surface.style.width} ${env.device.surface.style.height}`);

  env.device.scale.value = "fit";
  env.device.change(env.device.scale);
  await settle();
  check("every other scale takes the tall frame",
        env.device.frameImage.src === "device/x4-white.png",
        env.device.frameImage.src);

  env.device.scale.value = "pixels";
  env.device.change(env.device.scale);
  env.device.model.value = "x3";
  env.device.change(env.device.model);
  await settle();
  check("and the pair is per device",
        env.device.frameImage.src === "device/x3-white-1to1.png" &&
        env.device.surface.style.width === "671px",
        `${env.device.frameImage.src} ${env.device.surface.style.width}`);
}

// Shift turns the copy button into a download, and says so while it is held --
// the same bargain Build makes when it says Rebuild.
{
  const env = await loaded(fakeStorage(), undefined, {renderOk: true});
  await settle();
  // The title it starts with is the markup's, which test_preview_server.py
  // asserts; what this covers is the pair of icons and the swap below.
  check("the button copies by default",
        env.device.copyIcons[".as-copy"].hidden === false &&
        env.device.copyIcons[".as-download"].hidden === true,
        JSON.stringify(env.device.copyIcons));

  for (const listener of env.keys) listener({key: "Shift"});
  check("holding shift shows it will download instead",
        env.device.copyIcons[".as-copy"].hidden === true &&
        env.device.copyIcons[".as-download"].hidden === false &&
        /Download/.test(env.device.copy.title),
        env.device.copy.title);

  for (const listener of env.keyups) listener({key: "Shift"});
  check("and letting go puts it back",
        env.device.copyIcons[".as-copy"].hidden === false &&
        env.device.copyIcons[".as-download"].hidden === true,
        env.device.copy.title);
}

// The decoded bitmaps are the only page state the pipeline holds, so their
// two closes are the whole memory story: a newer page closes the one it
// replaces, and the newest is the one on the canvas.
{
  const env = await loaded(fakeStorage(), undefined, {renderOk: true});
  const first = env.fetches.bitmaps.at(-1);
  check("the first page is painted open",
        env.device.canvas.painted === first && first.closed === false,
        JSON.stringify(first));

  env.byName.gamma.value = "1.4";
  env.listeners.input({target: env.byName.gamma});
  await settle();
  await settle();
  const second = env.fetches.bitmaps.at(-1);
  check("a newer page closes the bitmap it replaces",
        second !== first && first.closed === true && second.closed === false,
        JSON.stringify(env.fetches.bitmaps));
  check("and the canvas shows the newest page",
        env.device.canvas.painted === second,
        JSON.stringify(env.device.canvas.painted));
}

// 78. Coverage decides what the page draws, so a tick has to redraw it. It
//     used to redraw only while the bundled fallback set was on, back when
//     coverage did nothing but choose which of those faces to load. That left
//     the one action a blank page had just asked for doing nothing at all:
//     the note says tick Arabic, you tick Arabic, and the page does not move.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  env.exportForm.elements.fallbacks.checked = false;
  const box = env.presetList.querySelectorAll().find(one => one.value === "reading");
  const before = env.fetches.bodies.length;
  box.checked = false;
  env.exportForm.on.input({target: box});
  await settle();
  check("a coverage tick redraws with the bundled faces off",
        env.fetches.bodies.length > before,
        `${before} -> ${env.fetches.bodies.length}`);
  check("and the redraw carries the coverage it was ticked to",
        env.fetches.bodies.at(-1).intervals !== undefined,
        JSON.stringify(env.fetches.bodies.at(-1).intervals));
}

// 79. A raw range is coverage too, and the page is held to it the same way.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  const before = env.fetches.bodies.length;
  env.exportForm.elements.ranges.value = "(0x0600-0x06FF)";
  env.exportForm.on.input({target: env.exportForm.elements.ranges});
  await settle();
  check("typing a range redraws", env.fetches.bodies.length > before,
        `${before} -> ${env.fetches.bodies.length}`);
  check("and the range reaches the server",
        env.fetches.bodies.at(-1).ranges === "(0x0600-0x06FF)",
        JSON.stringify(env.fetches.bodies.at(-1).ranges));
}

// 80. The other tick the page can be waiting on, marked the same way. A page
//     with holes in it names two moves in its note; the box for the one that
//     is still off says which without being read for.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 7 });
  const box = env.exportForm.elements.fallbacks;
  check("the bundled faces box is marked while it is off and needed",
        box.parentElement.classes.has("needed") === true,
        [...box.parentElement.classes].join());
}

// 81. And not while it is already on: the faces are being asked for, so the
//     answer is Fetch and marking the box would point at the wrong move.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 7 });
  const box = env.exportForm.elements.fallbacks;
  // Through the box, as a press does, so the redraw it causes is the one that
  // decides the mark rather than the mark being set by hand.
  box.checked = true;
  env.exportForm.on.input({target: box});
  await settle();
  check("and not marked once it is on",
        box.parentElement.classes.has("needed") === false,
        [...box.parentElement.classes].join());
}

// 82. Nothing waiting, nothing marked, which is every page that draws.
{
  const env = await loaded(fakeStorage(), DEFAULTS, { renderOk: true });
  check("no tick is marked on a page that draws",
        env.exportForm.elements.fallbacks.parentElement.classes.has("needed")
        === false);
}

// 83. The last link in the chain. The box is on, so the faces are being asked
//     for, and Fetch shows itself exactly when they are not here yet: that is
//     the move left to make, so that is what is marked.
{
  const env = await loaded(fakeStorage(), { ...DEFAULTS, fallbacks: "" },
                           { renderOk: true, undrawn: 7 });
  const button = env.sandbox.document.getElementById("fetch");
  const box = env.exportForm.elements.fallbacks;
  check("with the faces absent the offer is showing", button.hidden === false);
  box.checked = true;
  env.exportForm.on.input({target: box});
  await settle();
  check("the box is no longer the move once it is on",
        box.parentElement.classes.has("needed") === false,
        [...box.parentElement.classes].join());
  check("and Fetch is", button.classes.has("needed") === true,
        [...button.classes].join());
}

// 84. Faces present and the box on, and the page still has holes: the family
//     and its fallbacks between them have no glyph, and no control here
//     changes that. Marking one would send somebody to press it for nothing.
{
  const env = await loaded(fakeStorage(), DEFAULTS,
                           { renderOk: true, undrawn: 7 });
  const button = env.sandbox.document.getElementById("fetch");
  const box = env.exportForm.elements.fallbacks;
  box.checked = true;
  env.exportForm.on.input({target: box});
  await settle();
  check("nothing is marked when there is nothing left to press",
        box.parentElement.classes.has("needed") === false
        && button.classes.has("needed") === false,
        `${[...box.parentElement.classes]} / ${[...button.classes]}`);
}

process.exit(failures ? 1 : 0);
