// Drawing a schema: the words of the reference form become labels, linked by a click on the
// governing word then on its dependent, or by an arrow dragged from one to the other. The written
// schema follows the drawing, and the drawing follows the written schema when it is edited. Without
// this script, the schema is written by hand in its field.
(() => {
  "use strict";

  const DRAG_DISTANCE = 6;
  const DELAY = 500;
  const RETRY_DELAY = 1000;
  const OBJECT = "obj";
  const PASSIVE = "nsubj:pass";
  const PHRASE = "sp";
  const REGIME = "reg";
  const SLOT = "*";
  const BRACKET_ROW = 24;
  const SVG = "http://www.w3.org/2000/svg";
  const EDGE = /^(\p{L}+)\s*[-—–]\s*([a-zA-Z:|\s]+?)\s*(?:->|→)\s*(\p{L}+|\*)$/u;
  // A unit named in a reference form, then its words there: [rēs pūblica;rem pūblicam].
  const MARK = /\[([^[\];]*);([^[\];]*)\]/g;

  // The search form of a Latin word, as the server writes lemmas.
  function normalizeLatin(text) {
    return text
      .replace(/æ/gi, "ae")
      .replace(/œ/gi, "oe")
      .normalize("NFD")
      .replace(/\p{M}/gu, "")
      .toLowerCase()
      .replace(/v/g, "u")
      .replace(/j/g, "i");
  }

  // The reference form without its marks: the words as they are written.
  function plainForm(text) {
    return text.replace(MARK, (_whole, _name, words) => words);
  }

  // A name as the server compares names.
  function nameKey(name) {
    return normalizeLatin(name.trim().split(/\s+/).join(" "));
  }

  function markNames(text) {
    return [...text.matchAll(MARK)].map((match) => nameKey(match[1]));
  }

  // The text with the first occurrence of words outside the marks put in a mark; null if none.
  function markWords(text, words, name) {
    let offset = 0;
    for (const match of [...text.matchAll(MARK), null]) {
      const end = match ? match.index : text.length;
      const place = text.slice(offset, end).indexOf(words);
      if (place >= 0) {
        const start = offset + place;
        return `${text.slice(0, start)}[${name};${words}]${text.slice(start + words.length)}`;
      }
      if (match) {
        offset = match.index + match[0].length;
      }
    }
    return null;
  }

  // The relations of a written schema, without checking it is a tree; null if it cannot be read.
  function parseLocally(text) {
    const triples = [];
    for (const part of text.split(";").map((piece) => piece.trim()).filter(Boolean)) {
      const match = EDGE.exec(part);
      if (!match) {
        return null;
      }
      const relations = match[2].split("|").map((relation) => relation.trim().toLowerCase());
      triples.push({
        head: normalizeLatin(match[1]),
        dependent: match[3] === SLOT ? SLOT : normalizeLatin(match[3]),
        relations: [...new Set(relations.filter(Boolean))],
      });
    }
    return triples;
  }

  function element(name, className, text) {
    const node = document.createElement(name);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  function button(label, action, className) {
    const node = element("button", className, label);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  function svgElement(name, attributes) {
    const node = document.createElementNS(SVG, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  }

  function setUp(builder, index) {
    const labels = builder.dataset;
    const input = document.getElementById(labels.input);
    if (!input) {
      return;
    }
    const source = labels.wordsFrom && input.form ? input.form.elements.namedItem(labels.wordsFrom) : null;
    const maxRelations = Number(labels.maxRelations) || 4;
    const canvas = builder.querySelector(".schema-canvas");
    const svg = builder.querySelector(".schema-arcs");
    const wordList = builder.querySelector(".schema-words");
    const linkList = builder.querySelector(".schema-links");
    const status = builder.querySelector(".schema-status");
    const problems = builder.querySelector(".schema-problems");
    const preview = builder.querySelector(".schema-preview");
    const linkPanel = builder.querySelector(".schema-link-panel");
    const relationSelect = linkPanel.querySelector(".schema-relation");
    const passiveRow = linkPanel.querySelector(".schema-passive");
    const passiveBox = linkPanel.querySelector(".schema-passive-box");
    const caseRow = linkPanel.querySelector(".schema-case");
    const caseSelect = linkPanel.querySelector(".schema-case-select");
    const componentBox = builder.querySelector(".schema-components");
    const componentList = builder.querySelector(".schema-component-list");
    const insertInput = builder.querySelector(".schema-insert-input");
    const insertResults = builder.querySelector(".schema-insert-results");
    const sourceTools = builder.querySelector(".schema-source-tools");
    const markPreview = sourceTools.querySelector(".form-mark-preview");
    const formProblems = sourceTools.querySelector(".schema-form-problems");
    const suggestionList = sourceTools.querySelector(".schema-suggestions");
    // The search of attestations of the page, filled with the lemmas of the schema.
    const searchForm = labels.search ? document.getElementById(labels.search) : null;
    const termFields = searchForm
      ? [1, 2, 3, 4, 5].map((number) => searchForm.elements.namedItem(`term${number}`)).filter(Boolean)
      : [];
    const keep = JSON.parse(labels.keep || "{}");
    const variants = linkPanel.querySelector(".schema-variants");
    const unlinkButton = linkPanel.querySelector(".schema-unlink");
    const wordPanel = builder.querySelector(".schema-word-panel");
    const lemmaInput = wordPanel.querySelector(".schema-lemma-input");
    const addInput = builder.querySelector(".schema-add-input");
    const markerId = `schema-arrow-${index}`;

    let words = [];
    let edges = [];
    // The units the server finds within the schema: their names, statuses, pages and lemmas.
    let components = [];
    // The units named in the reference form whose links already came into the drawing.
    const handledNames = new Set();
    let formRequest = 0;
    let formTimer = null;
    // Terms typed in the search are no longer filled from the schema; terms of a search already
    // made are kept unless they are those the schema gives.
    let searchTouched = false;
    let searchMade = termFields.length > 0 && new URLSearchParams(window.location.search).has("term1");
    let nextKey = 0;
    const removed = new Set();
    let chosen = null;
    let pending = null;
    let shownWord = null;
    let drag = null;
    let suppressClick = false;
    let request = 0;
    let checkTimer = null;
    let sourceTimer = null;

    // Words and links

    function byKey(key) {
      return words.find((word) => word.key === key);
    }

    function name(key) {
      const word = byKey(key);
      return word.slot ? labels.labelAny : word.form;
    }

    function lemmaOf(key) {
      const word = byKey(key);
      return word.slot ? SLOT : word.lemma;
    }

    function isLinked(key) {
      return edges.some((edge) => edge.head === key || edge.dependent === key);
    }

    function makeWord(form, lemmas, known, lemma) {
      const choices = lemmas.length ? lemmas : [normalizeLatin(form)];
      return {
        key: `w${nextKey++}`,
        form,
        lemmas: choices,
        lemma: lemma || choices[0],
        known,
        slot: false,
        added: false,
      };
    }

    function makeSlot() {
      return { key: `w${nextKey++}`, form: SLOT, lemmas: [], lemma: SLOT, known: true, slot: true, added: true };
    }

    function currentTriples() {
      return edges.map((edge) => ({
        head: lemmaOf(edge.head),
        dependent: lemmaOf(edge.dependent),
        relations: edge.relations,
      }));
    }

    // Links given by lemma, as the written schema gives them, attached to the words that have
    // these lemmas; a lemma no word has becomes a word of its own.
    function attach(triples) {
      const found = new Map();
      const wordFor = (lemma) => {
        if (!found.has(lemma)) {
          const taken = [...found.values()];
          let word =
            lemma === SLOT
              ? words.find((candidate) => candidate.slot)
              : words.find((candidate) => !candidate.slot && candidate.lemma === lemma && !taken.includes(candidate)) ||
                words.find(
                  (candidate) => !candidate.slot && candidate.lemmas.includes(lemma) && !taken.includes(candidate),
                );
          if (!word) {
            word = lemma === SLOT ? makeSlot() : makeWord(lemma, [lemma], true);
            word.added = true;
            words.push(word);
          }
          if (!word.slot) {
            word.lemma = lemma;
          }
          found.set(lemma, word);
        }
        return found.get(lemma);
      };
      edges = triples.map((triple) => ({
        head: wordFor(triple.head).key,
        dependent: wordFor(triple.dependent).key,
        relations: [...triple.relations],
      }));
      // A word added for a lemma the reference form now gives is no longer needed.
      words = words.filter(
        (word) =>
          !word.added ||
          word.slot ||
          isLinked(word.key) ||
          !words.some((other) => !other.added && !other.slot && other.lemma === word.lemma),
      );
    }

    // The links from the root down, as the server orders them.
    function orderedEdges() {
      const position = new Map(words.map((word, place) => [word.key, place]));
      const dependents = new Set(edges.map((edge) => edge.dependent));
      const queue = words.filter((word) => !dependents.has(word.key) && isLinked(word.key)).map((word) => word.key);
      const ordered = [];
      while (queue.length) {
        const key = queue.shift();
        edges
          .filter((edge) => edge.head === key && !ordered.includes(edge))
          .sort((first, second) => position.get(first.dependent) - position.get(second.dependent))
          .forEach((edge) => {
            ordered.push(edge);
            queue.push(edge.dependent);
          });
      }
      return ordered.concat(edges.filter((edge) => !ordered.includes(edge)));
    }

    function writtenSchema() {
      return orderedEdges()
        .map((edge) => `${lemmaOf(edge.head)} -${edge.relations.join("|")}-> ${lemmaOf(edge.dependent)}`)
        .join("; ");
    }

    // The drawing changed: the written schema follows, then the server checks and counts it.
    function write() {
      input.value = writtenSchema();
      scheduleCheck(input.value, false);
    }

    function say(text) {
      status.textContent = text;
    }

    // Relations

    // A regime with its case reads "régime (ablatif)".
    function relationName(code) {
      const [kind, subtype] = code.split(":");
      if (kind === REGIME && subtype) {
        const choice = [...caseSelect.options].find((candidate) => candidate.value === subtype);
        return `${relationName(REGIME)} (${choice ? choice.textContent : subtype})`;
      }
      const option = [...relationSelect.options].find((candidate) => candidate.value === code);
      return option ? option.dataset.short : code;
    }

    function relationText(relations) {
      const passive = relations.includes(OBJECT) && relations.includes(PASSIVE);
      const shown = passive ? relations.filter((relation) => relation !== PASSIVE) : relations;
      const text = shown.map(relationName).join(` ${labels.labelOr} `);
      return passive ? `${text} (${labels.labelPassive})` : text;
    }

    function ensureOption(select, code) {
      if (code && ![...select.options].some((option) => option.value === code)) {
        const option = element("option", "", code);
        option.value = code;
        option.dataset.short = code;
        select.append(option);
      }
    }

    function variantSelects() {
      return [...variants.querySelectorAll("select")];
    }

    // The passive is offered with an object, the case with a regime.
    function updateChoices() {
      passiveRow.hidden = ![relationSelect, ...variantSelects()].some((select) => select.value === OBJECT);
      caseRow.hidden = relationSelect.value !== REGIME;
    }

    function addVariant(code) {
      const row = element("p", "schema-variant");
      const select = relationSelect.cloneNode(true);
      select.className = "schema-variant-relation";
      select.setAttribute("aria-label", labels.labelVariant);
      ensureOption(select, code);
      select.value = code;
      select.addEventListener("change", updateChoices);
      const remove = button(
        labels.labelRemoveVariant,
        () => {
          row.remove();
          updateChoices();
        },
        "link-button",
      );
      row.append(`${labels.labelOr} `, select, " ", remove);
      variants.append(row);
      return select;
    }

    function setRelations(relations) {
      variants.replaceChildren();
      const passive = relations.includes(OBJECT) && relations.includes(PASSIVE);
      let shown = passive ? relations.filter((relation) => relation !== PASSIVE) : relations;
      const [kind, subtype] = (shown[0] || "").split(":");
      caseSelect.value = kind === REGIME ? subtype || "" : "";
      if (kind === REGIME) {
        shown = [REGIME, ...shown.slice(1)];
      }
      // A new object also finds the passive, unless the box is unticked.
      passiveBox.checked = relations.length === 0 || passive;
      ensureOption(relationSelect, shown[0] || "");
      relationSelect.value = shown[0] || "";
      shown.slice(1).forEach(addVariant);
      updateChoices();
    }

    function chosenRelations() {
      const values = [relationSelect, ...variantSelects()].map((select) => select.value).filter(Boolean);
      if (relationSelect.value === REGIME && caseSelect.value) {
        values[0] = `${REGIME}:${caseSelect.value}`;
      }
      const relations = [...new Set(values)];
      if (relations.includes(OBJECT) && passiveBox.checked && !relations.includes(PASSIVE)) {
        relations.push(PASSIVE);
      }
      return relations;
    }

    // Panels

    function closePanels() {
      linkPanel.hidden = true;
      wordPanel.hidden = true;
      pending = null;
      shownWord = null;
    }

    function focusWord(key) {
      const token = wordList.querySelector(`[data-key="${key}"] .schema-token`);
      if (token) {
        token.focus();
      }
    }

    function choose(key) {
      chosen = key;
      wordList.querySelectorAll(".schema-word").forEach((item) => {
        const on = item.dataset.key === key;
        item.classList.toggle("is-chosen", on);
        item.querySelector(".schema-token").setAttribute("aria-pressed", on ? "true" : "false");
      });
      if (key !== null) {
        say(labels.labelChosen.replace("%s", name(key)));
      }
    }

    function showPair() {
      linkPanel.querySelector(".schema-head").textContent = name(pending.head);
      linkPanel.querySelector(".schema-dependent").textContent = name(pending.dependent);
      unlinkButton.hidden = !pending.edge;
    }

    function findEdge(head, dependent) {
      return edges.find((edge) => edge.head === head && edge.dependent === dependent) || null;
    }

    function openLinkPanel(head, dependent) {
      closePanels();
      choose(null);
      if (byKey(head).slot) {
        say(labels.labelSlotHead);
        return;
      }
      pending = { head, dependent, edge: findEdge(head, dependent) };
      setRelations(pending.edge ? pending.edge.relations : []);
      showPair();
      say("");
      linkPanel.hidden = false;
      relationSelect.focus();
    }

    // Whether a word depends, directly or not, on another one.
    function dependsOn(key, ancestor, links) {
      const seen = new Set();
      let current = key;
      while (current !== undefined && !seen.has(current)) {
        if (current === ancestor) {
          return true;
        }
        seen.add(current);
        const link = links.find((edge) => edge.dependent === current);
        current = link ? link.head : undefined;
      }
      return false;
    }

    function confirmLink() {
      const relations = chosenRelations();
      if (!relations.length) {
        say(labels.labelChoose);
        relationSelect.focus();
        return;
      }
      const { head, dependent, edge } = pending;
      let message = "";
      if (edge) {
        edge.relations = relations;
      } else {
        // The link the other way round gives way to this one.
        let links = edges.filter((link) => !(link.head === dependent && link.dependent === head));
        if (dependsOn(head, dependent, links)) {
          say(labels.labelCycle);
          return;
        }
        const previous = links.find((link) => link.dependent === dependent);
        if (previous) {
          links = links.filter((link) => link !== previous);
          message = labels.labelReplaced.replace("%s", name(dependent));
        } else if (links.length >= maxRelations) {
          say(labels.labelTooMany);
          return;
        }
        links.push({ head, dependent, relations });
        edges = links;
      }
      closePanels();
      render();
      write();
      focusWord(dependent);
      // A preposition just linked is chosen, so that the next click links its regime.
      if (relations.includes(PHRASE) && !edges.some((link) => link.head === dependent)) {
        choose(dependent);
        message = [message, labels.labelRegime.replace("%s", name(dependent))].filter(Boolean).join(" ");
      }
      say(message);
    }

    function swapLink() {
      if (byKey(pending.dependent).slot) {
        say(labels.labelSlotHead);
        return;
      }
      const { head, dependent } = pending;
      pending = { head: dependent, dependent: head, edge: findEdge(dependent, head) };
      showPair();
    }

    function unlink() {
      const { edge, dependent } = pending;
      edges = edges.filter((link) => link !== edge);
      closePanels();
      render();
      write();
      focusWord(dependent);
    }

    function openWordPanel(key) {
      closePanels();
      choose(null);
      const word = byKey(key);
      shownWord = key;
      wordPanel.querySelector(".schema-word-title").textContent = word.slot
        ? labels.labelAny
        : labels.labelLemmaOf.replace("%s", word.form);
      const choices = wordPanel.querySelector(".schema-lemma-choices");
      choices.replaceChildren(
        ...word.lemmas.map((lemma) => {
          const choice = button(lemma, () => setLemma(key, lemma), lemma === word.lemma ? "button" : "button button-quiet");
          choice.lang = "la";
          choice.setAttribute("aria-pressed", lemma === word.lemma ? "true" : "false");
          return choice;
        }),
      );
      choices.hidden = word.slot;
      wordPanel.querySelector(".schema-lemma-other").hidden = word.slot;
      lemmaInput.value = "";
      wordPanel.hidden = false;
      (choices.querySelector("button") || wordPanel.querySelector(".schema-word-remove")).focus();
    }

    function setLemma(key, text) {
      const lemma = normalizeLatin(text.trim());
      if (!/^\p{L}+$/u.test(lemma)) {
        say(labels.labelBadLemma);
        lemmaInput.focus();
        return;
      }
      byKey(key).lemma = lemma;
      closePanels();
      render();
      write();
      focusWord(key);
    }

    function removeWord(key) {
      const word = byKey(key);
      if (!word.added) {
        removed.add(word.form.toLowerCase());
      }
      words = words.filter((candidate) => candidate.key !== key);
      edges = edges.filter((edge) => edge.head !== key && edge.dependent !== key);
      closePanels();
      render();
      write();
    }

    // Server

    // A request that finds no server (while it restarts, for instance) is tried once more; the
    // message of a failure goes away as soon as the server answers again.
    async function getJson(address, params, retries = 1) {
      const url = new URL(address, window.location.origin);
      Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
      let response;
      try {
        response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
      } catch (error) {
        if (retries > 0) {
          await new Promise((resolve) => window.setTimeout(resolve, RETRY_DELAY));
          return getJson(address, params, retries - 1);
        }
        throw error;
      }
      if (!response.ok) {
        throw new Error(response.statusText);
      }
      const data = await response.json();
      if (status.textContent === labels.labelError) {
        say("");
      }
      return data;
    }

    async function lemmasOf(text) {
      return (await getJson(labels.lemmasUrl, { formes: text })).words;
    }

    // Units to insert, found by their reference form.
    async function searchUnits() {
      const text = insertInput.value.trim();
      if (!text) {
        return;
      }
      let found;
      try {
        found = (await getJson(labels.unitsUrl, { fiche: text })).units;
      } catch {
        say(labels.labelError);
        return;
      }
      insertResults.replaceChildren(
        ...found.map((unit) => {
          const item = element("li");
          const choice = button(unit.reference_form, () => (source ? buildOn(unit) : insertUnit(unit)), "link-button");
          choice.lang = "la";
          item.append(choice, " ", element("span", "schema-component-status", unit.status));
          return item;
        }),
      );
      insertResults.hidden = found.length === 0;
      say(found.length ? "" : labels.labelNoUnit);
      const first = insertResults.querySelector("button");
      if (first) {
        first.focus();
      }
    }

    // The links of a unit join those drawn, on the words that have their lemmas.
    function insertUnit(unit) {
      const triples = currentTriples();
      for (const edge of unit.edges) {
        const existing = triples.find((triple) => triple.dependent === edge.dependent);
        if (!existing) {
          triples.push({ head: edge.head, dependent: edge.dependent, relations: [...edge.relations] });
        } else if (existing.head !== edge.head) {
          say(labels.labelInsertConflict.replace("%s", edge.dependent));
          return false;
        }
      }
      if (triples.length > maxRelations) {
        say(labels.labelTooMany);
        return false;
      }
      attach(triples);
      insertResults.replaceChildren();
      insertResults.hidden = true;
      insertInput.value = "";
      closePanels();
      render();
      write();
      say(labels.labelInserted.replace("%s", unit.reference_form));
      return true;
    }

    // A unit the new one is built on: its mark joins the reference form, where its words are to
    // be written as they appear, and its links join the drawing.
    async function buildOn(unit) {
      const mark = `[${unit.reference_form};${unit.reference_form}]`;
      const before = source.value.trim();
      source.value = before ? `${before} ${mark}` : mark;
      handledNames.add(nameKey(unit.reference_form));
      await rebuild();
      insertUnit(unit);
      const end = source.value.length - 1;
      source.focus();
      source.setSelectionRange(end - unit.reference_form.length, end);
      scheduleFormHelp();
    }

    // A known unit found in the words of the reference form: marked there, linked in the drawing.
    async function useSuggestion(suggestion) {
      const marked = markWords(source.value, suggestion.excerpt, suggestion.reference_form);
      if (marked === null) {
        say(labels.labelWordsGone.replace("%s", suggestion.excerpt));
        return;
      }
      source.value = marked;
      handledNames.add(nameKey(suggestion.reference_form));
      await rebuild();
      insertUnit(suggestion);
      scheduleFormHelp();
    }

    function scheduleFormHelp() {
      clearTimeout(formTimer);
      formTimer = setTimeout(formHelp, DELAY);
    }

    // The server reads the reference form: the units its marks name, and the units to suggest.
    async function formHelp() {
      const current = ++formRequest;
      if (!source.value.trim()) {
        showFormHelp({ parts: [], suggestions: [], errors: [] });
        return;
      }
      let data;
      try {
        data = await getJson(labels.formUrl, { forme: source.value, schema: input.value });
      } catch {
        if (current === formRequest) {
          say(labels.labelError);
        }
        return;
      }
      if (current !== formRequest) {
        return;
      }
      // A unit newly named in the form brings its links into the drawing.
      for (const part of data.parts) {
        if (part.name && !handledNames.has(nameKey(part.name))) {
          handledNames.add(nameKey(part.name));
          if (part.unit) {
            insertUnit(part.unit);
          }
        }
      }
      showFormHelp(data);
    }

    function unitLink(unit) {
      const link = element("a", "", unit.reference_form);
      link.href = unit.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.lang = "la";
      return link;
    }

    // A marked piece of the reference form, as the page of the unit shows it.
    function previewPart(part) {
      if (!part.name) {
        return document.createTextNode(part.text);
      }
      const entry = element("span", "form-mark-entry");
      entry.lang = "fr";
      if (part.unit) {
        entry.append(unitLink(part.unit), " ", element("span", "form-mark-status", part.unit.status));
      } else {
        const name = element("span", "", part.name);
        name.lang = "la";
        entry.append(name, " ", element("span", "form-mark-status", labels.labelNoUnitNamed));
      }
      if (part.others.length) {
        const others = element("span", "form-mark-others", ` · ${labels.labelSameName} `);
        part.others.forEach((other, index) => {
          others.append(index ? ", " : "", unitLink(other), " ", element("span", "form-mark-status", other.status));
        });
        entry.append(others);
      }
      const bubble = element("span", "form-mark-bubble");
      bubble.setAttribute("role", "tooltip");
      bubble.append(entry);
      const mark = element("span", "form-mark");
      mark.tabIndex = 0;
      mark.append(element("mark", "form-mark-words", part.text), bubble);
      return mark;
    }

    function showFormHelp(data) {
      formProblems.textContent = data.errors.join(" ");
      markPreview.replaceChildren(...data.parts.map(previewPart));
      markPreview.hidden = !data.parts.some((part) => part.name);
      const [before, after] = labels.labelSuggestion.split("%s");
      suggestionList.replaceChildren(
        ...data.suggestions.map((suggestion) => {
          const item = element("li");
          const words = element("span", "", suggestion.excerpt);
          words.lang = "la";
          item.append(
            before,
            words,
            after,
            " ",
            unitLink(suggestion),
            " ",
            element("span", "form-mark-status", suggestion.status),
            " ",
            button(labels.labelUse, () => useSuggestion(suggestion), "button button-quiet"),
          );
          return item;
        }),
      );
      suggestionList.hidden = data.suggestions.length === 0;
    }

    // The search of attestations looks for the lemmas of the schema, the root first.
    function fillSearch(found) {
      if (!termFields.length || searchTouched) {
        return;
      }
      const lemmas = [];
      found.forEach((edge) =>
        [edge.head, edge.dependent].forEach((lemma) => {
          if (lemma !== SLOT && !lemmas.includes(lemma)) {
            lemmas.push(lemma);
          }
        }),
      );
      if (!lemmas.length) {
        return;
      }
      if (searchMade) {
        searchMade = false;
        if (!termFields.every((field, index) => field.value === (lemmas[index] || ""))) {
          searchTouched = true;
          return;
        }
      }
      termFields.forEach((field, index) => {
        field.value = lemmas[index] || "";
        const mode = searchForm.elements.namedItem(`mode${index + 1}`);
        if (mode && lemmas[index]) {
          mode.value = "lemma";
        }
      });
      const more = searchForm.querySelector(".panel-more");
      if (more && [...more.querySelectorAll("input[name^='term']")].some((field) => field.value)) {
        more.open = true;
      }
    }

    // The words of the reference form, keeping the lemma chosen for a word still there. Without
    // ``triples``, the links kept are those drawn once the lemmas come back, so that links added
    // meanwhile (a unit named in the form) are not lost.
    async function rebuild(triples) {
      const text = source ? plainForm(source.value) : "";
      let found = [];
      if (text.trim()) {
        try {
          found = await lemmasOf(text);
        } catch {
          say(labels.labelError);
          found = words.filter((word) => !word.added).map((word) => ({ ...word }));
        }
      }
      const links = triples || currentTriples();
      const previous = new Map();
      words
        .filter((word) => !word.added)
        .forEach((word) => previous.has(word.form) || previous.set(word.form, word.lemma));
      const kept = words.filter((word) => word.added);
      words = found
        .filter((word) => !removed.has(word.form.toLowerCase()))
        .map((word) => makeWord(word.form, word.lemmas, word.known, previous.get(word.form)));
      words.push(...kept);
      attach(links);
    }

    function scheduleCheck(text, redraw) {
      clearTimeout(checkTimer);
      checkTimer = setTimeout(() => check(text, redraw), DELAY);
    }

    // The server checks the written schema and counts it; a schema written by hand is drawn.
    async function check(text, redraw) {
      const current = ++request;
      problems.textContent = "";
      if (!text.trim()) {
        preview.textContent = "";
        showComponents([]);
        if (redraw) {
          attach([]);
          render();
        }
        return;
      }
      const params = { schema: text };
      if (labels.slot) {
        params.case_vide = "1";
      }
      if (labels.count) {
        params.compter = "1";
        preview.textContent = labels.labelCounting;
      }
      let data;
      try {
        data = await getJson(labels.checkUrl, params);
      } catch {
        if (current === request) {
          preview.textContent = "";
          say(labels.labelError);
        }
        return;
      }
      if (current !== request) {
        return;
      }
      if (data.errors.length) {
        problems.textContent = data.errors.join(" ");
        preview.textContent = "";
        const triples = redraw ? parseLocally(text) : null;
        if (triples) {
          attach(triples);
          render();
        }
        showComponents([]);
        return;
      }
      if (redraw) {
        attach(data.edges);
        render();
      }
      showComponents(data.components || []);
      showPreview(data);
      fillSearch(data.edges);
      if (source) {
        scheduleFormHelp();
      }
    }

    function showComponents(found) {
      components = found;
      componentList.replaceChildren(
        ...found.map((component) => {
          const item = element("li");
          const link = element("a", "", component.reference_form);
          link.href = component.url;
          link.target = "_blank";
          link.rel = "noopener";
          link.lang = "la";
          item.append(link, " ", element("span", "schema-component-status", component.status));
          return item;
        }),
      );
      componentBox.hidden = found.length === 0;
      drawArcs();
    }

    function showPreview(data) {
      preview.replaceChildren();
      if (!labels.count || !("core" in data)) {
        return;
      }
      if (data.exceeded) {
        preview.textContent = labels.labelTooLong;
        return;
      }
      if (data.core === 0) {
        preview.textContent = labels.labelNone.replace("%s", data.version);
        return;
      }
      preview.append(data.core === 1 ? labels.labelOne : labels.labelMany.replace("%s", data.core), " · ");
      const link = element("a", "", labels.labelSee);
      link.href = data.search_url;
      link.target = "_blank";
      link.rel = "noopener";
      preview.append(link);
    }

    // Drawing

    function renderWord(word) {
      const item = element("li", "schema-word");
      item.dataset.key = word.key;
      const linked = isLinked(word.key);
      item.classList.toggle("is-outside", !linked);
      item.classList.toggle("is-slot", word.slot);
      item.classList.toggle("is-chosen", chosen === word.key);
      const token = element("button", "schema-token");
      token.type = "button";
      token.setAttribute("aria-pressed", chosen === word.key ? "true" : "false");
      const form = element("span", "schema-form", word.slot ? labels.labelAny : word.form);
      if (!word.slot) {
        form.lang = "la";
      }
      token.append(form);
      const hints = [];
      if (!word.slot) {
        const lemma = element("span", "schema-lemma", word.lemma);
        lemma.lang = "la";
        if (word.lemmas.length > 1) {
          lemma.append(element("span", "schema-dot", "•"));
          hints.push(labels.labelAmbiguous);
        }
        if (!word.known) {
          lemma.classList.add("is-unknown");
          hints.push(labels.labelUnknown);
        }
        token.append(lemma);
      }
      if (!linked) {
        hints.push(labels.labelOutside);
      }
      if (hints.length) {
        token.title = hints.join(" · ");
      }
      const menu = button("▾", () => openWordPanel(word.key), "schema-word-menu");
      menu.setAttribute("aria-label", word.slot ? labels.labelAny : labels.labelLemmaOf.replace("%s", word.form));
      item.append(token, menu);
      return item;
    }

    function renderLinks() {
      linkList.replaceChildren(
        ...orderedEdges().map((edge) => {
          const item = element("li");
          item.append(
            button(
              `${name(edge.head)} → ${relationText(edge.relations)} → ${name(edge.dependent)}`,
              () => openLinkPanel(edge.head, edge.dependent),
              "link-button",
            ),
          );
          return item;
        }),
      );
      linkList.hidden = edges.length === 0;
    }

    function render() {
      wordList.replaceChildren(...words.map(renderWord));
      builder.querySelector(".schema-empty").hidden = words.length > 0;
      renderLinks();
      drawArcs();
    }

    function anchor(key) {
      const token = wordList.querySelector(`[data-key="${key}"] .schema-token`);
      const box = token.getBoundingClientRect();
      const origin = canvas.getBoundingClientRect();
      return {
        x: box.left - origin.left + canvas.scrollLeft + box.width / 2,
        y: box.top - origin.top + canvas.scrollTop,
        bottom: box.bottom - origin.top + canvas.scrollTop,
      };
    }

    // The words of a unit found within the schema: the linked words that have its lemmas.
    function componentKeys(component) {
      return words
        .filter((word) => !word.slot && isLinked(word.key) && component.lemmas.includes(word.lemma))
        .map((word) => word.key);
    }

    // Under the words of each unit found within the schema, a bracket with its name, one row
    // for each unit, so that units sharing words or with words apart stay readable.
    function drawBrackets() {
      components.forEach((component, row) => {
        const keys = componentKeys(component);
        if (keys.length < 2) {
          return;
        }
        const points = keys.map(anchor);
        const left = Math.min(...points.map((point) => point.x));
        const right = Math.max(...points.map((point) => point.x));
        const y = Math.max(...points.map((point) => point.bottom)) + 10 + row * BRACKET_ROW;
        const ticks = points.map((point) => `M ${point.x} ${point.bottom + 3} L ${point.x} ${y}`).join(" ");
        const group = svgElement("g", { class: "schema-bracket" });
        const label = svgElement("text", { x: (left + right) / 2, y: y + 13, class: "schema-bracket-label", "text-anchor": "middle" });
        label.textContent = component.reference_form;
        group.append(svgElement("path", { d: `${ticks} M ${left} ${y} L ${right} ${y}`, class: "schema-bracket-line" }), label);
        svg.append(group);
      });
    }

    // Longer links are drawn higher, so that their labels, at the top of the arcs, stay apart.
    function arcHeight(edge, position) {
      return 30 + 24 * (Math.abs(position.get(edge.head) - position.get(edge.dependent)) - 1);
    }

    function arrowDefinition() {
      const definitions = svgElement("defs", {});
      const marker = svgElement("marker", {
        id: markerId,
        viewBox: "0 0 10 10",
        refX: "9",
        refY: "5",
        markerWidth: "7",
        markerHeight: "7",
        orient: "auto-start-reverse",
      });
      marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "schema-arrow" }));
      definitions.append(marker);
      return definitions;
    }

    function drawArcs() {
      const position = new Map(words.map((word, place) => [word.key, place]));
      const highest = Math.max(0, ...edges.map((edge) => arcHeight(edge, position)));
      canvas.style.paddingTop = `${Math.max(56, highest + 28)}px`;
      canvas.style.paddingBottom = components.length ? `${components.length * BRACKET_ROW + 14}px` : "";
      svg.replaceChildren(arrowDefinition());
      svg.setAttribute("width", canvas.scrollWidth);
      svg.setAttribute("height", canvas.scrollHeight);
      for (const edge of edges) {
        const start = anchor(edge.head);
        const end = anchor(edge.dependent);
        const height = arcHeight(edge, position);
        const direction = end.x > start.x ? 1 : -1;
        const x1 = start.x + 8 * direction;
        const x2 = end.x - 8 * direction;
        const y = start.y - 2;
        const path = `M ${x1} ${y} C ${x1} ${y - height}, ${x2} ${y - height}, ${x2} ${y}`;
        const group = svgElement("g", { class: "schema-arc" });
        const label = svgElement("text", {
          x: (x1 + x2) / 2,
          y: y - height * 0.75 - 5,
          class: "schema-arc-label",
          "text-anchor": "middle",
        });
        label.textContent = relationText(edge.relations);
        group.append(
          svgElement("path", { d: path, class: "schema-arc-hit" }),
          svgElement("path", { d: path, class: "schema-arc-line", "marker-end": `url(#${markerId})` }),
          label,
        );
        group.addEventListener("click", () => openLinkPanel(edge.head, edge.dependent));
        svg.append(group);
      }
      drawBrackets();
    }

    function drawDrag(x, y) {
      let line = svg.querySelector(".schema-drag");
      if (!line) {
        line = svgElement("path", { class: "schema-drag", "marker-end": `url(#${markerId})` });
        svg.append(line);
      }
      const start = anchor(drag.key);
      const origin = canvas.getBoundingClientRect();
      const endX = x - origin.left + canvas.scrollLeft;
      const endY = y - origin.top + canvas.scrollTop;
      line.setAttribute("d", `M ${start.x} ${start.y} Q ${(start.x + endX) / 2} ${Math.min(start.y, endY) - 40} ${endX} ${endY}`);
    }

    function stopDrag() {
      drag = null;
      builder.classList.remove("is-dragging");
      const line = svg.querySelector(".schema-drag");
      if (line) {
        line.remove();
      }
    }

    // Gestures

    wordList.addEventListener("click", (event) => {
      const token = event.target.closest(".schema-token");
      if (!token) {
        return;
      }
      if (suppressClick) {
        suppressClick = false;
        return;
      }
      const key = token.closest(".schema-word").dataset.key;
      if (chosen === null) {
        closePanels();
        if (byKey(key).slot) {
          say(labels.labelSlotHead);
        } else {
          choose(key);
        }
      } else if (chosen === key) {
        choose(null);
        say("");
      } else {
        openLinkPanel(chosen, key);
      }
    });

    wordList.addEventListener("pointerdown", (event) => {
      const token = event.target.closest(".schema-token");
      if (!token || event.button !== 0) {
        return;
      }
      drag = {
        key: token.closest(".schema-word").dataset.key,
        x: event.clientX,
        y: event.clientY,
        pointer: event.pointerId,
        moving: false,
      };
    });

    window.addEventListener("pointermove", (event) => {
      if (!drag || event.pointerId !== drag.pointer) {
        return;
      }
      if (!drag.moving) {
        if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < DRAG_DISTANCE) {
          return;
        }
        drag.moving = true;
        builder.classList.add("is-dragging");
        closePanels();
        choose(null);
      }
      event.preventDefault();
      drawDrag(event.clientX, event.clientY);
    });

    window.addEventListener("pointerup", (event) => {
      if (!drag || event.pointerId !== drag.pointer) {
        return;
      }
      const { key, moving } = drag;
      stopDrag();
      if (!moving) {
        return;
      }
      // The click that ends a drag on the same word is not a choice.
      suppressClick = true;
      window.setTimeout(() => {
        suppressClick = false;
      }, 0);
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const item = target ? target.closest(".schema-word") : null;
      if (item && wordList.contains(item) && item.dataset.key !== key) {
        openLinkPanel(key, item.dataset.key);
      }
    });

    window.addEventListener("pointercancel", stopDrag);

    function onKeydown(event) {
      if (event.key === "Escape") {
        if (!linkPanel.hidden || !wordPanel.hidden) {
          const key = pending ? pending.dependent : shownWord;
          closePanels();
          if (key) {
            focusWord(key);
          }
        } else if (chosen !== null) {
          choose(null);
          say("");
        }
        event.preventDefault();
      } else if (event.key === "Enter" && event.target.matches("input[type='text']")) {
        // Enter in the fields of the drawing does not send the form.
        event.preventDefault();
        if (event.target === addInput) {
          addWord();
        } else if (event.target === insertInput) {
          searchUnits();
        } else if (event.target === lemmaInput && shownWord) {
          setLemma(shownWord, lemmaInput.value);
        }
      }
    }

    builder.addEventListener("keydown", onKeydown);
    // The field of the unit built on sits under the reference form, outside the drawing.
    sourceTools.addEventListener("keydown", onKeydown);

    async function addWord() {
      const text = addInput.value.trim();
      if (!text) {
        return;
      }
      let found;
      try {
        found = await lemmasOf(text);
      } catch {
        say(labels.labelError);
        return;
      }
      if (!found.length) {
        say(labels.labelBadLemma);
        return;
      }
      const word = makeWord(found[0].form, found[0].lemmas, found[0].known);
      word.added = true;
      words.push(word);
      addInput.value = "";
      render();
      write();
      say("");
    }

    linkPanel.querySelector(".schema-confirm").addEventListener("click", confirmLink);
    linkPanel.querySelector(".schema-swap").addEventListener("click", swapLink);
    unlinkButton.addEventListener("click", unlink);
    linkPanel.querySelector(".schema-add-variant").addEventListener("click", () => addVariant("").focus());
    relationSelect.addEventListener("change", updateChoices);
    builder.querySelectorAll(".schema-cancel").forEach((cancel) =>
      cancel.addEventListener("click", () => {
        const key = pending ? pending.dependent : shownWord;
        closePanels();
        if (key) {
          focusWord(key);
        }
      }),
    );
    wordPanel.querySelector(".schema-lemma-set").addEventListener("click", () => setLemma(shownWord, lemmaInput.value));
    wordPanel.querySelector(".schema-word-remove").addEventListener("click", () => removeWord(shownWord));
    builder.querySelector(".schema-add-word").addEventListener("click", addWord);
    builder.querySelector(".schema-insert-search").addEventListener("click", searchUnits);
    const addSlot = builder.querySelector(".schema-add-slot");
    if (addSlot) {
      addSlot.addEventListener("click", () => {
        if (!words.some((word) => word.slot)) {
          words.push(makeSlot());
          render();
        }
      });
    }

    // The written schema, edited by hand, is drawn again; the reference form gives new words.
    input.addEventListener("input", () => scheduleCheck(input.value, true));
    if (source) {
      source.addEventListener("input", () => {
        scheduleFormHelp();
        clearTimeout(sourceTimer);
        sourceTimer = setTimeout(async () => {
          await rebuild();
          render();
          write();
        }, DELAY);
      });
    }
    new ResizeObserver(() => drawArcs()).observe(canvas);

    async function start() {
      const initial = input.value;
      const written = element("details", "schema-written");
      written.append(element("summary", "", labels.labelWritten));
      builder.after(written);
      written.append(input);
      builder.hidden = false;
      if (source) {
        // Under the reference form: the unit it is built on, its marks, the units to suggest.
        (source.parentElement || source).after(sourceTools);
        const insert = builder.querySelector(".schema-insert");
        insert.querySelector("label").firstChild.textContent = `${labels.labelBuiltOn} `;
        sourceTools.prepend(insert, insertResults);
        sourceTools.hidden = false;
        markNames(source.value).forEach((name) => handledNames.add(name));
        if (source.value.trim()) {
          scheduleFormHelp();
        }
      }
      if (searchForm) {
        // A search reloads the page: what is written in the form comes back with it.
        searchForm.addEventListener("submit", () => {
          Object.entries(keep).forEach(([fieldName, parameter]) => {
            const field = input.form ? input.form.elements.namedItem(fieldName) : null;
            if (!field) {
              return;
            }
            let hidden = searchForm.querySelector(`input[type="hidden"][name="${parameter}"]`);
            if (!hidden) {
              hidden = document.createElement("input");
              hidden.type = "hidden";
              hidden.name = parameter;
              searchForm.append(hidden);
            }
            hidden.value = field.value;
            hidden.disabled = !field.value;
          });
        });
      }
      await rebuild([]);
      render();
      if (initial.trim()) {
        await check(initial, true);
      }
    }

    start();
  }

  document.querySelectorAll(".schema-builder").forEach(setUp);
})();
