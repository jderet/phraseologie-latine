// Reading a work: the words of one occurrence light up together, and a click on a word opens a
// panel with the units it belongs to and its analysis. Without this script the page still shows
// every underline, and the list of the units of the page leads to their entries.
(() => {
  "use strict";

  const article = document.querySelector(".reading");
  const text = document.querySelector(".reading-rows");
  if (!article || !text) {
    return;
  }
  const labels = article.dataset;
  let lit = [];
  let selected = null;
  let panel = null;
  let request = 0;

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

  function select(word) {
    if (selected) {
      selected.classList.remove("is-selected");
    }
    selected = word;
    if (word) {
      word.classList.add("is-selected");
    }
  }

  function panelBody() {
    if (!panel) {
      panel = document.createElement("aside");
      panel.className = "reading-panel";
      panel.setAttribute("aria-live", "polite");
      const close = document.createElement("button");
      close.type = "button";
      close.className = "link-button reading-panel-close";
      close.textContent = labels.labelClose;
      close.addEventListener("click", closePanel);
      const body = document.createElement("div");
      body.className = "reading-panel-body";
      panel.append(close, body);
      document.body.append(panel);
    }
    panel.hidden = false;
    return panel.querySelector(".reading-panel-body");
  }

  function closePanel() {
    if (panel) {
      panel.hidden = true;
    }
    select(null);
  }

  async function showWord(word) {
    select(word);
    const body = panelBody();
    const current = ++request;
    const passage = word.closest(".reading-passage");
    const back = `${window.location.pathname}${window.location.search}${passage ? `#${passage.id}` : ""}`;
    const url = new URL(labels.wordUrl.replace(/\/0\/$/, `/${word.dataset.t}/`), window.location.origin);
    url.searchParams.set("fragment", "1");
    url.searchParams.set("retour", back);
    body.textContent = labels.labelLoading;
    try {
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error(response.statusText);
      }
      const html = await response.text();
      if (current === request) {
        // The HTML is rendered and escaped by the server, as for the panel of the editor.
        body.innerHTML = html;
      }
    } catch {
      if (current === request) {
        body.textContent = labels.labelError;
      }
    }
  }

  text.addEventListener("mouseover", (event) => light(event.target.closest("[data-t]")));
  text.addEventListener("mouseleave", () => light(null));
  text.addEventListener("click", (event) => {
    const word = event.target.closest("[data-t]");
    if (word && !event.target.closest("a")) {
      showWord(word);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePanel();
    }
  });
})();
