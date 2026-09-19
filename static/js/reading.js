// Reading a work: the words of one occurrence light up together, a click on a word opens a panel
// with the units it belongs to and its analysis, and in the mode "annoter" clicks choose the words
// of an attestation. Without this script the page still shows every underline, and the list of the
// units of the page leads to their entries.
(() => {
  "use strict";

  const article = document.querySelector(".reading");
  const text = document.querySelector(".reading-rows");
  if (!article || !text) {
    return;
  }
  const labels = article.dataset;
  const annotating = labels.annotating === "1";
  const chosen = new Map();
  let lit = [];
  let selected = null;
  let panel = null;
  let bar = null;
  let request = 0;

  // Text sizes for the reading page: a choice of the reader, remembered from page to page.
  const scaleBox = article.querySelector("[data-scale]");
  if (scaleBox) {
    const sizes = { S: 0.9, M: 1, L: 1.15 };
    const caption = document.createElement("span");
    caption.textContent = scaleBox.dataset.label;
    scaleBox.append(caption);
    const apply = (name) => {
      article.style.setProperty("--reading-scale", String(sizes[name]));
      try {
        window.localStorage.setItem("reading-scale", name);
      } catch {
        // Private browsing: the choice simply lasts for the page.
      }
      scaleBox.querySelectorAll("button").forEach((element) => {
        element.setAttribute("aria-pressed", String(element.textContent === name));
      });
    };
    for (const name of Object.keys(sizes)) {
      scaleBox.append(button(name, () => apply(name), "pill"));
    }
    let saved = null;
    try {
      saved = window.localStorage.getItem("reading-scale");
    } catch {
      saved = null;
    }
    apply(sizes[saved] ? saved : "M");
  }

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

  function button(label, action, className) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = className;
    element.textContent = label;
    element.addEventListener("click", action);
    return element;
  }

  function panelBody() {
    if (!panel) {
      panel = document.createElement("aside");
      panel.className = "reading-panel";
      panel.setAttribute("aria-live", "polite");
      const body = document.createElement("div");
      body.className = "reading-panel-body";
      panel.append(button(labels.labelClose, closePanel, "link-button reading-panel-close"), body);
      // A search inside the panel stays in the panel.
      panel.addEventListener("submit", (event) => {
        const form = event.target;
        if (!form.matches("[data-panel-form]")) {
          return;
        }
        event.preventDefault();
        const url = new URL(form.action, window.location.origin);
        new FormData(form).forEach((value, name) => url.searchParams.set(name, value));
        load(url);
      });
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

  async function load(url) {
    const body = panelBody();
    const current = ++request;
    url.searchParams.set("fragment", "1");
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

  // The reading page to come back to, at the passage of a word.
  function backTo(word) {
    const passage = word.closest(".reading-passage");
    return `${window.location.pathname}${window.location.search}${passage ? `#${passage.id}` : ""}`;
  }

  function showWord(word) {
    select(word);
    const url = new URL(labels.wordUrl.replace(/\/0\/$/, `/${word.dataset.t}/`), window.location.origin);
    url.searchParams.set("retour", backTo(word));
    load(url);
  }

  function inTextOrder() {
    return [...chosen.values()].sort((first, second) =>
      first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
    );
  }

  function selectionBar() {
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "reading-selection";
      bar.setAttribute("role", "region");
      bar.setAttribute("aria-label", labels.labelChosen);
      const words = document.createElement("p");
      words.className = "reading-selection-words";
      const actions = document.createElement("p");
      actions.className = "reading-selection-actions";
      // A panel for the words chosen: a public reading note, or the private notebook.
      const keep = (address) => () => {
        const chosenWords = inTextOrder();
        if (!chosenWords.length) {
          return;
        }
        const url = new URL(address, window.location.origin);
        url.searchParams.set("mots", chosenWords.map((word) => word.dataset.t).join(","));
        url.searchParams.set("retour", backTo(chosenWords[0]));
        load(url);
      };
      actions.append(
        button(labels.labelAttach, attach, "button"),
        button(labels.labelSighting, sight, "button button-quiet"),
        button(labels.labelReadingNote, keep(labels.readingNoteUrl), "button button-quiet"),
        button(labels.labelHighlight, keep(labels.highlightUrl), "button button-quiet"),
        button(labels.labelNote, keep(labels.noteUrl), "button button-quiet"),
        button(labels.labelClear, clearChoice, "link-button"),
      );
      bar.append(words, actions);
      document.body.append(bar);
    }
    return bar;
  }

  function showChoice() {
    const element = selectionBar();
    element.hidden = chosen.size === 0;
    const words = inTextOrder().map((word) => word.textContent);
    element.querySelector(".reading-selection-words").textContent = `${labels.labelChosen} ${words.join(" … ")}`;
  }

  function toggle(word) {
    const key = word.dataset.t;
    if (chosen.has(key)) {
      chosen.delete(key);
      word.classList.remove("is-chosen");
    } else {
      chosen.set(key, word);
      word.classList.add("is-chosen");
    }
    showChoice();
  }

  function clearChoice() {
    chosen.forEach((word) => word.classList.remove("is-chosen"));
    chosen.clear();
    showChoice();
  }

  // An occurrence of a known schema, suggested in pointillé: its key names the unit and the words.
  function showSuggestion(mark, word) {
    const [, unit, ...words] = mark.dataset.o.split("_");
    const url = new URL(labels.suggestionUrl, window.location.origin);
    url.searchParams.set("fiche", unit);
    url.searchParams.set("mots", words.join(","));
    url.searchParams.set("retour", backTo(word));
    load(url);
  }

  // A sighting of a reader, dashed: its key names the sighting and its words.
  function showSighting(mark, word) {
    const [, sighting, ...words] = mark.dataset.o.split("_");
    const url = new URL(labels.annotateUrl, window.location.origin);
    url.searchParams.set("mots", words.join(","));
    url.searchParams.set("reperage", sighting);
    url.searchParams.set("retour", backTo(word));
    load(url);
  }

  // Words where there is phraseology, recorded without choosing an entry.
  function sight() {
    const words = inTextOrder();
    if (!words.length) {
      return;
    }
    const url = new URL(labels.sightingUrl, window.location.origin);
    url.searchParams.set("mots", words.map((word) => word.dataset.t).join(","));
    url.searchParams.set("retour", backTo(words[0]));
    load(url);
  }

  function attach() {
    const words = inTextOrder();
    if (!words.length) {
      return;
    }
    const url = new URL(labels.annotateUrl, window.location.origin);
    url.searchParams.set("mots", words.map((word) => word.dataset.t).join(","));
    url.searchParams.set("retour", backTo(words[0]));
    load(url);
  }

  text.addEventListener("mouseover", (event) => light(event.target.closest("[data-t]")));
  text.addEventListener("mouseleave", () => light(null));
  text.addEventListener("click", (event) => {
    const word = event.target.closest("[data-t]");
    if (!word || event.target.closest("a")) {
      return;
    }
    if (annotating) {
      const suggestion = event.target.closest('[data-o^="s_"]');
      const sighting = event.target.closest('[data-o^="r_"]');
      if (suggestion) {
        showSuggestion(suggestion, word);
      } else if (sighting) {
        showSighting(sighting, word);
      } else {
        toggle(word);
      }
    } else {
      showWord(word);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePanel();
    }
  });
})();
