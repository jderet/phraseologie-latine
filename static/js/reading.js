// Reading a work: the words of one occurrence light up together. Without this script the page
// still shows every underline, and the list of the units of the page leads to their entries.
(() => {
  "use strict";

  const text = document.querySelector(".reading-rows");
  if (!text) {
    return;
  }
  let lit = [];

  // The occurrences a word belongs to, from the closest line to the farthest.
  function occurrencesOf(word) {
    const keys = [];
    let mark = word.closest("[data-o]");
    while (mark) {
      keys.push(mark.dataset.o);
      mark = mark.parentElement.closest("[data-o]");
    }
    return keys;
  }

  function light(word) {
    lit.forEach((element) => element.classList.remove("is-lit"));
    lit = [];
    if (!word) {
      return;
    }
    for (const key of occurrencesOf(word)) {
      text.querySelectorAll(`[data-o="${key}"]`).forEach((element) => {
        element.classList.add("is-lit");
        lit.push(element);
      });
    }
  }

  text.addEventListener("mouseover", (event) => light(event.target.closest("[data-t]")));
  text.addEventListener("mouseleave", () => light(null));
})();
