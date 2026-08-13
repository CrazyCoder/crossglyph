import {form, samplePicker} from "./dom.js";
import {attempt, savePage} from "./remember.js";

// --- the sample text ------------------------------------------------------
// Kept apart from the page settings: it is what you are looking at rather than
// a setting of the reader's, so neither reset button throws it away.
//
// Two things are remembered, in two slots on purpose. Choosing a language must
// never cost somebody the text they wrote, and switching back has to return
// it, which one shared slot cannot do.
export const TEXT = "crossglyph.text";       // your own words, if you have any
export const CHOICE = "crossglyph.sample";   // which entry the picker is on

//: The entry that holds your own text. First in the list, and the value the
//: markup declares, so a page whose /defaults never answered still has one.
export const CUSTOM = "";

//: tag -> {name, text}, as /defaults serves it, in the order it serves them.
export const samples = new Map();

export function savedChoice() {
  return attempt(() => localStorage.getItem(CHOICE), null);
}

export function rememberChoice(tag) {
  attempt(() => localStorage.setItem(CHOICE, tag));
}

export function customText() {
  return attempt(() => localStorage.getItem(TEXT), "") || "";
}

export function saveText() {
  const value = form.elements.text.value;
  attempt(() => value ? localStorage.setItem(TEXT, value)
                      : localStorage.removeItem(TEXT));
}

export function loadText() {
  // Only your own text can go back this early, because a preset's words arrive
  // with /defaults. Filling the box now and replacing it a moment later would
  // flash text nobody chose.
  if (savedChoice()) return;
  form.elements.text.value = customText();
}

export function fillSamples(table) {
  for (const [tag, sample] of Object.entries(table || {})) {
    samples.set(tag, sample);
    samplePicker.add(new Option(sample.name, tag));
  }
}

//: Chinese is chosen by script and a browser reports a country, so the two have
//: to be mapped: zh-CN, zh-SG and zh-MY are written in simplified characters,
//: zh-TW, zh-HK and zh-MO in traditional. A bare `zh` has to pick one, and
//: simplified has the larger readership.
const CHINESE = {
  "zh": "zh-Hans", "zh-cn": "zh-Hans", "zh-sg": "zh-Hans",
  "zh-my": "zh-Hans", "zh-hans": "zh-Hans",
  "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
  "zh-hant": "zh-Hant",
};

// Which preset the browser's own languages ask for. They come in preference
// order, so the first that matches wins; a region is dropped, since a preset
// is per language and `de-AT` reads the German one.
export function preferredSample(languages) {
  for (const raw of languages || []) {
    const parts = String(raw).toLowerCase().split("-");
    if (parts[0] === "zh") {
      const picked = CHINESE[parts.slice(0, 2).join("-")] || CHINESE.zh;
      if (samples.has(picked)) return picked;
      continue;
    }
    if (samples.has(parts[0])) return parts[0];
  }
  // English rather than Custom: an empty box on a first visit says less about
  // a font than a language most people here read a little of.
  return samples.has("en") ? "en" : CUSTOM;
}

export function showSample(tag) {
  const known = samples.has(tag);
  samplePicker.value = known ? tag : CUSTOM;
  form.elements.text.value = known ? samples.get(tag).text : customText();
}

// A preset carries the hyphenation language with it when the core has patterns
// for that language, and leaves it alone when it has none: choosing the
// Japanese sample must not quietly go on hyphenating the page as English.
export function followLanguage(tag) {
  const el = form.elements.language;
  if (!tag || !el || ![...el.options].some(option => option.value === tag)) {
    return;
  }
  el.value = tag;
  savePage();
}

export function sampleChosen() {
  const tag = samplePicker.value;
  rememberChoice(tag);
  form.elements.text.value = samples.has(tag) ? samples.get(tag).text
                                              : customText();
  followLanguage(tag);
}

export function typedInBox() {
  // Typing makes it yours. The presets are what the tool ships and stay as
  // they are; Custom is where anything you write is kept. Moving the picker
  // here is what stops your own words going missing the next time you look at
  // another language.
  if (samplePicker.value !== CUSTOM) {
    samplePicker.value = CUSTOM;
    rememberChoice(CUSTOM);
  }
  saveText();
}

// What the picker opens on: what you last chose, or, the first time, whatever
// the browser says you read. A stored choice always wins -- detection is what
// happens once, not something that overrides what you have since picked.
export function restoreSample(languages) {
  const saved = savedChoice();
  const first = saved === null;
  showSample(first ? preferredSample(languages) : saved);
  // The hyphenation language is not set from here even on a first visit. It is
  // one of the page settings, and those may have been remembered from a visit
  // before this picker existed -- moving it would overwrite a choice somebody
  // made. start.js sets it only when there are no page settings at all.
  if (first) rememberChoice(samplePicker.value);
  return first;
}
