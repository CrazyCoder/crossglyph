// --- how far a build has got ----------------------------------------------
// A build is minutes with the fallbacks on and the server takes the sizes one
// at a time, so "building…" and a hung process look identical for the whole of
// it. The stream carries a count from its first line, which is a fraction the
// panel actually knows rather than a spinner standing in for one.
//
// It is drawn as one of the panel's own hairlines filling. Every row here is
// separated by one, so progress in that material reads as part of the panel;
// a bar laid on top would be the loudest thing in it, and loudest for the one
// state that ends by itself.
export const progressRow = document.getElementById("progress");
export const bar = document.getElementById("bar");
export const barFill = document.getElementById("bar-fill");
export const progressWhat = document.getElementById("progress-what");
export const progressCount = document.getElementById("progress-count");

// When the run started, for the estimate. Per build rather than per size.
let startedAt = 0;

//: A duration as a reader says it: 45s, 2m, 2m 10s.
export function spellDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60), rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

// What is left, from what the sizes so far have cost.
//
// Held back until two are done and five seconds have gone. The first size pays
// every one-off cost of the run -- opening the fallback faces, the charmap
// pass -- so an estimate drawn from it alone is out by a factor, and a wrong
// number is worse than no number on the one screen someone is waiting at.
export function timeLeft(done, total, elapsed) {
  if (done < 2 || elapsed < 5000 || done >= total) return "";
  const seconds = Math.round((elapsed / done) * (total - done) / 1000);
  return seconds < 5 ? "" : `${spellDuration(seconds)} left`;
}

// Before the plan arrives there is no total, and the save that may come first
// is a round trip of its own. The rule sweeps rather than sitting at nothing,
// and carries no aria-valuenow, which is how a progressbar says it cannot say.
export function startProgress(what) {
  startedAt = performance.now();
  progressRow.hidden = false;
  bar.classList.add("waiting");
  // At nothing, not at whatever the last run ended on: the first counted step
  // has to fill from empty rather than back down from a bar already part full.
  barFill.style.width = "0%";
  bar.removeAttribute("aria-valuenow");
  bar.setAttribute("aria-valuetext", what);
  progressWhat.textContent = what;
  progressCount.textContent = "";
}

//: Bytes as somebody watching a download would say them. A fetch counts in
//: bytes rather than in files because one face is four fifths of the set, and
//: "12 of 13" would race to the end and then sit there for a minute.
export function spellBytes(count) {
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} MB`;
  if (count >= 1e3) return `${Math.round(count / 1e3)} kB`;
  return `${count} B`;
}

// `spell` is how the two numbers are said. Sizes are a count of themselves and
// need nothing; bytes are not worth reading as digits.
export function showProgress(done, total, what, spell = String) {
  progressRow.hidden = false;
  bar.classList.remove("waiting");
  barFill.style.width = `${total > 0 ? Math.round(done / total * 100) : 0}%`;
  bar.setAttribute("aria-valuemax", String(total));
  bar.setAttribute("aria-valuenow", String(done));
  const left = timeLeft(done, total, performance.now() - startedAt);
  const count = `${spell(done)} of ${spell(total)}` + (left ? `, ${left}` : "");
  bar.setAttribute("aria-valuetext", what ? `${what}, ${count}` : count);
  progressWhat.textContent = what;
  progressCount.textContent = count;
}

// Whatever ended it: a finished build, a refusal, a dropped connection. The
// sentence the build leaves behind is the note's job, and a bar sitting at
// some fraction under it would say the run is still going.
export function endProgress() {
  progressRow.hidden = true;
  bar.classList.remove("waiting");
  // Emptied while it is out of the document, so the next run opens at nothing
  // rather than animating down from the last one's finish.
  barFill.style.width = "0%";
}
