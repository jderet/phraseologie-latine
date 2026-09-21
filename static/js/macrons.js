// Typing long vowels in every Latin field of the site: two identical vowels in a row become
// one vowel with a macron ("aa" gives "ā"). Typing the vowel once more gives the two plain
// vowels back, for the words that really hold one ("cooperio", "Aaron"); "i" has one more
// step, because "iī" is a form Latin writes ("iī", "diī"): "ii" gives "ī", "iii" gives "iī",
// and "iiii" gives the three plain vowels back.
//
// The rule only answers keystrokes: pasted text is left alone, and without this script the
// fields work as before, with the "=" shortcut of the editor or the macron bar.
(() => {
  "use strict";

  const LONG = { a: "ā", e: "ē", i: "ī", o: "ō", u: "ū", y: "ȳ", A: "Ā", E: "Ē", I: "Ī", O: "Ō", U: "Ū", Y: "Ȳ" };

  // What the field shows after each keystroke of a run of the same vowel, the first one left
  // out: it is the character the browser has just inserted, with nothing to change.
  function steps(vowel) {
    const long = LONG[vowel];
    if (vowel === "i" || vowel === "I") {
      return [long, vowel + long, vowel + vowel + vowel];
    }
    return [long, vowel + vowel];
  }

  // The run of vowels being typed in a field: which vowel, how many keystrokes, and where the
  // caret was left. A run is broken as soon as the caret moves elsewhere.
  const runs = new WeakMap();

  function isLatinField(node) {
    return (
      (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) &&
      node.getAttribute("lang") === "la" &&
      !node.readOnly &&
      !node.disabled
    );
  }

  function handle(field, vowel) {
    const caret = field.selectionStart;
    if (caret !== field.selectionEnd) {
      runs.delete(field);
      return;
    }
    const run = runs.get(field);
    // The keystroke has to follow the previous one of the run, on the same vowel.
    const following = run && run.vowel === vowel && run.caret === caret - 1;
    const step = following ? run.step + 1 : 1;
    const shown = steps(vowel);
    if (step > 1) {
      // Replace what the previous keystroke had left, plus the vowel just inserted.
      const written = step === 2 ? vowel : shown[step - 3];
      field.setRangeText(shown[step - 2], caret - written.length - 1, caret, "end");
    }
    if (step > shown.length) {
      // The run ends on the keystroke that gives the plain vowels back.
      runs.delete(field);
      return;
    }
    runs.set(field, { vowel, step, caret: field.selectionStart });
  }

  document.addEventListener("input", (event) => {
    const field = event.target;
    if (!isLatinField(field)) {
      return;
    }
    if (event.inputType !== "insertText" || !LONG[event.data]) {
      runs.delete(field);
      return;
    }
    handle(field, event.data);
  });
})();
