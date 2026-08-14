// --- how far something has got ---------------------------------------------
// A build is minutes with the fallbacks on, and an update is a megabyte and a
// half over whatever link is there: "building…" and a hung process look
// identical for the whole of it. Each stream carries a count, which is a
// fraction the page actually knows rather than a spinner standing in for one.
//
// It is drawn as one of the panel's own hairlines filling. Every row here is
// separated by one, so progress in that material reads as part of the panel;
// a bar laid on top would be the loudest thing in it, and loudest for the one
// state that ends by itself.

//: A duration as a reader says it: 45s, 2m, 2m 10s.
export function spellDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60), rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

// What is left, at the rate the sizes have been landing. Sizes run across a
// pool, so this is throughput rather than the cost of one of them, which is
// the number that extrapolates: the pool stays full while there is work.
//
// Held back until two are done and five seconds have gone. Nothing has landed
// while the workers are still starting, and the first to arrive have paid
// every one-off cost of the run between them -- opening the fallback faces,
// the charmap pass. A wrong number is worse than no number on the one screen
// somebody is waiting at.
export function timeLeft(done, total, elapsed) {
  if (done < 2 || elapsed < 5000 || done >= total) return "";
  const seconds = Math.round((elapsed / done) * (total - done) / 1000);
  return seconds < 5 ? "" : `${spellDuration(seconds)} left`;
}

//: Bytes as somebody watching a download would say them. A fetch counts in
//: bytes rather than in files because one face is four fifths of the set, and
//: "12 of 13" would race to the end and then sit there for a minute.
export function spellBytes(count) {
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} MB`;
  if (count >= 1e3) return `${Math.round(count / 1e3)} kB`;
  return `${count} B`;
}

// One bar, over the row it is drawn in. Two of these exist -- the build's, in
// the export panel, and the update's, in the island under the specimen -- and
// each keeps its own start time, so what one reports says nothing about when
// the other began.
//
// `mark` is shown when the run starts and left alone after that: a bar hidden
// behind a tab has to leave something on the tab, and what it has to say
// outlasts the run. Whoever owns the mark clears it, since only they know when
// it has been seen. A bar nothing can hide gets none.
export function progressBar(row, mark) {
  const bar = row.querySelector(".bar");
  const fill = row.querySelector(".bar-fill");
  const what = row.querySelector(".progress-what");
  const count = row.querySelector(".progress-count");
  // When this run started, for the estimate. Per run rather than per size.
  let startedAt = 0;

  return {
    // Before the plan arrives there is no total, and the save that may come
    // first is a round trip of its own. The rule sweeps rather than sitting at
    // nothing, and carries no aria-valuenow, which is how a progressbar says
    // it cannot say.
    start(text) {
      startedAt = performance.now();
      row.hidden = false;
      if (mark) mark.hidden = false;
      bar.classList.add("waiting");
      // At nothing, not at whatever the last run ended on: the first counted
      // step has to fill from empty rather than back down from a bar already
      // part full.
      fill.style.width = "0%";
      bar.removeAttribute("aria-valuenow");
      bar.setAttribute("aria-valuetext", text);
      what.textContent = text;
      count.textContent = "";
    },

    // `spell` is how the two numbers are said. Sizes are a count of themselves
    // and need nothing; bytes are not worth reading as digits.
    show(done, total, text, spell = String) {
      row.hidden = false;
      bar.classList.remove("waiting");
      fill.style.width = `${total > 0 ? Math.round(done / total * 100) : 0}%`;
      bar.setAttribute("aria-valuemax", String(total));
      bar.setAttribute("aria-valuenow", String(done));
      const left = timeLeft(done, total, performance.now() - startedAt);
      const said = `${spell(done)} of ${spell(total)}` +
        (left ? `, ${left}` : "");
      bar.setAttribute("aria-valuetext", text ? `${text}, ${said}` : said);
      what.textContent = text;
      count.textContent = said;
    },

    // Whatever ended it: a finished build, a refusal, a dropped connection.
    // The sentence the run leaves behind is the note's job, and a bar sitting
    // at some fraction under it would say the run is still going.
    end() {
      row.hidden = true;
      bar.classList.remove("waiting");
      // Emptied while it is out of the document, so the next run opens at
      // nothing rather than animating down from the last one's finish.
      fill.style.width = "0%";
    },
  };
}
