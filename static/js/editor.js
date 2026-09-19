// Translation editor: saves each sentence when it is left, types macrons, searches the corpus,
// prepares justifications and shows the tools of the active sentence in the tabs of the side
// panel. Without this script the page still works: the form saves every sentence at once, the
// panel shows its sections one after the other, and justifications are reached from the page
// of the version.
(() => {
  "use strict";

  const LONG = { a: "ā", e: "ē", i: "ī", o: "ō", u: "ū", y: "ȳ", A: "Ā", E: "Ē", I: "Ī", O: "Ō", U: "Ū", Y: "Ȳ" };
  const SHORT = Object.fromEntries(Object.entries(LONG).map(([short, long]) => [long, short]));
  const SAVE_DELAY = 1500;

  const editor = document.getElementById("editor");
  if (!editor) {
    return;
  }
  const labels = editor.dataset;
  const csrfToken = editor.querySelector("[name=csrfmiddlewaretoken]").value;
  const fields = [...editor.querySelectorAll("textarea[data-save-url]")];
  const bar = document.getElementById("macron-bar");
  const panels = [...document.querySelectorAll(".row-panel")];
  const panelHint = document.querySelector(".panel-hint");
  const states = new Map(fields.map((field) => [field, { saved: field.value }]));
  let activeField = null;
  let submitting = false;

  // "a=" becomes "ā"; "=" typed after a long vowel gives back the short vowel and "=".
  function typeMacron(field) {
    const end = field.selectionStart;
    if (end !== field.selectionEnd || end < 2 || field.value[end - 1] !== "=") {
      return;
    }
    const previous = field.value[end - 2];
    if (LONG[previous]) {
      field.setRangeText(LONG[previous], end - 2, end, "end");
    } else if (SHORT[previous]) {
      field.setRangeText(`${SHORT[previous]}=`, end - 2, end, "end");
    }
  }

  function showStatus(field, text, isError = false) {
    const status = field.parentElement.querySelector(".save-status");
    status.textContent = text;
    status.classList.toggle("is-error", isError);
  }

  async function send(field, state) {
    const text = field.value;
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken);
    body.append("text", text);
    showStatus(field, labels.labelSaving);
    try {
      const response = await fetch(field.dataset.saveUrl, {
        method: "POST",
        body,
        credentials: "same-origin",
      });
      const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
      if (!isJson) {
        throw new Error(response.statusText);
      }
      const data = await response.json();
      state.saved = text;
      if (response.ok) {
        showStatus(field, labels.labelSaved);
        showUnits(field);
        forgetSentence(field);
        if (data.status) {
          setRowStatus(field, data.status);
        }
      } else {
        showStatus(field, data.errors.join(" "), true);
      }
    } catch {
      showStatus(field, labels.labelError, true);
    }
  }

  // Resolves when the sentence is saved, including a change made while it was being saved.
  function save(field) {
    const state = states.get(field);
    clearTimeout(state.timer);
    if (state.pending) {
      state.again = true;
      return state.pending;
    }
    if (field.value === state.saved) {
      return Promise.resolve();
    }
    state.pending = send(field, state).finally(() => {
      state.pending = null;
      if (state.again) {
        state.again = false;
        return save(field);
      }
      return undefined;
    });
    return state.pending;
  }

  function justifyLink(field) {
    return document.querySelector(`.justify-link[data-segment="${field.dataset.segment}"]`);
  }

  // The link to justify a choice carries the selected Latin words and their position.
  function followSelection(field) {
    const link = justifyLink(field);
    if (!link) {
      return;
    }
    const url = new URL(link.href);
    const selected = field.value.slice(field.selectionStart, field.selectionEnd);
    const excerpt = selected.trim();
    if (excerpt) {
      url.searchParams.set("extrait", excerpt);
      url.searchParams.set("debut", String(field.selectionStart + selected.indexOf(excerpt)));
    } else {
      url.searchParams.delete("extrait");
      url.searchParams.delete("debut");
    }
    link.href = url.toString();
  }

  // Known units of the saved sentence, in its panel. The HTML is rendered and escaped by the
  // server, as for the corpus search results.
  const unitsShown = new Map();

  async function showUnits(field) {
    const box = document.querySelector(`.row-units[data-segment="${field.dataset.segment}"]`);
    const saved = states.get(field).saved;
    if (!box || unitsShown.get(field) === saved) {
      return;
    }
    unitsShown.set(field, saved);
    box.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(`${box.dataset.unitsUrl}?fragment=1`, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error(response.statusText);
      }
      box.innerHTML = await response.text();
    } catch {
      unitsShown.delete(field);
      box.textContent = labels.labelUnitsError;
    } finally {
      box.removeAttribute("aria-busy");
    }
  }

  function activate(field) {
    for (const row of editor.querySelectorAll(".bitext-row.is-active")) {
      row.classList.remove("is-active");
    }
    field.closest(".bitext-row").classList.add("is-active");
    field.after(bar);
    bar.hidden = false;
    activeField = field;
    for (const panel of panels) {
      panel.hidden = panel.dataset.segment !== field.dataset.segment;
    }
    if (panelHint) {
      panelHint.hidden = true;
    }
    showUnits(field);
    loadTab(currentTab);
  }

  // Status of each sentence: to translate, draft, translated, reviewed; the bar of progress
  // follows.
  const STATUSES = ["todo", "draft", "translated", "reviewed"];
  const statusLabels = {
    todo: labels.statusTodo,
    draft: labels.statusDraft,
    translated: labels.statusTranslated,
    reviewed: labels.statusReviewed,
  };

  function setRowStatus(field, status) {
    const row = field.closest(".bitext-row");
    row.dataset.status = status;
    const dot = row.querySelector("[data-status-dot]");
    if (dot) {
      dot.className = `status-dot status-${status}`;
      dot.title = statusLabels[status] || "";
    }
    for (const button of row.querySelectorAll("[data-set-status]")) {
      button.setAttribute("aria-pressed", String(button.dataset.setStatus === status));
    }
    updateProgress();
  }

  function updateProgress() {
    const rows = [...editor.querySelectorAll(".bitext-row[data-status]")];
    const total = rows.length || 1;
    let offset = 0;
    for (const status of STATUSES) {
      const count = rows.filter((row) => row.dataset.status === status).length;
      const share = (count * 100) / total;
      const part = document.querySelector(`.status-part[data-status="${status}"]`);
      if (part) {
        part.setAttribute("x", offset.toFixed(3));
        part.setAttribute("width", share.toFixed(3));
      }
      const number = document.querySelector(`[data-count="${status}"]`);
      if (number) {
        number.textContent = String(count);
      }
      offset += share;
    }
  }

  async function markStatus(field, status) {
    await save(field);
    const row = field.closest(".bitext-row");
    const button = row.querySelector(`[data-set-status="${status}"]`);
    if (!button) {
      return false;
    }
    const body = new FormData();
    body.append("csrfmiddlewaretoken", csrfToken);
    body.append("status", status);
    try {
      const response = await fetch(button.formAction, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) {
        showStatus(field, data.errors.join(" "), true);
        return false;
      }
      setRowStatus(field, data.status);
      return true;
    } catch {
      showStatus(field, labels.labelError, true);
      return false;
    }
  }

  editor.addEventListener("click", (event) => {
    const button = event.target.closest("[data-set-status]");
    if (!button) {
      return;
    }
    event.preventDefault();
    const field = button.closest(".bitext-row").querySelector("textarea[data-save-url]");
    markStatus(field, button.dataset.setStatus);
  });

  // Latin taken from the panel (memory, glossary): the whole sentence, or the selection.
  document.addEventListener("mousedown", (event) => {
    if (event.target.closest("[data-use-latin]")) {
      event.preventDefault();
    }
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-use-latin]");
    // A term marked in a source sentence goes to the Latin of that sentence.
    const row = button && button.closest(".bitext-row");
    const field = row ? row.querySelector("textarea[data-save-url]") : activeField;
    if (!button || !field) {
      return;
    }
    event.preventDefault();
    const text = button.dataset.useLatin;
    if (button.dataset.mode === "replace") {
      field.setRangeText(text, 0, field.value.length, "end");
    } else {
      const before = field.value.slice(0, field.selectionStart);
      const spaced = before && !/\s$/.test(before) ? ` ${text}` : text;
      field.setRangeText(spaced, field.selectionStart, field.selectionEnd, "end");
    }
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.focus();
  });

  // Forms of the panel (comments): sent without leaving the page, then the tab is reloaded.
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest(".editor-panel form[data-panel-form]");
    if (!form) {
      return;
    }
    event.preventDefault();
    const body = new FormData(form, event.submitter);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        body,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) {
        window.alert(data.errors.join(" "));
        return;
      }
      loadTab(currentTab, true);
    } catch {
      window.alert(labels.labelError);
    }
  });

  // Tabs of the side panel: one section at a time, the choice kept for the next visit.
  const tabList = document.querySelector(".panel-tabs");
  const tabButtons = tabList ? [...tabList.querySelectorAll("[role=tab]")] : [];
  const tabPanels = [...document.querySelectorAll(".panel-tab")];
  const TAB_KEY = "editor-tab";
  let currentTab = tabButtons.length ? tabButtons[0].dataset.tab : null;
  // Fragments already loaded, by tab and sentence; a saved sentence forgets its own.
  const loaded = new Map();

  function readStoredTab() {
    try {
      return window.localStorage.getItem(TAB_KEY);
    } catch {
      return null;
    }
  }

  function storeTab(name) {
    try {
      window.localStorage.setItem(TAB_KEY, name);
    } catch {
      // Storage may be refused: the tab is simply not remembered.
    }
  }

  function showTab(name, focus = false) {
    const button = tabButtons.find((candidate) => candidate.dataset.tab === name);
    if (!button) {
      return;
    }
    currentTab = name;
    for (const candidate of tabButtons) {
      const selected = candidate === button;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    }
    for (const panel of tabPanels) {
      panel.hidden = panel.dataset.tab !== name;
    }
    storeTab(name);
    if (focus) {
      button.focus();
    }
    loadTab(name);
  }

  function segmentOf(field) {
    return field ? field.dataset.segment : null;
  }

  // Loads the fragment of a tab for the active sentence. The HTML is rendered and escaped by
  // the server, as for the corpus search results.
  async function loadTab(name, force = false) {
    const panel = tabPanels.find((candidate) => candidate.dataset.tab === name);
    const segment = segmentOf(activeField);
    if (!panel || !panel.dataset.fragmentUrl || !segment) {
      return;
    }
    const key = `${name}:${segment}`;
    const body = panel.querySelector(".panel-body");
    if (!force && loaded.get(key) === "done" && body.dataset.segment === segment) {
      return;
    }
    body.setAttribute("aria-busy", "true");
    body.textContent = labels.labelLoading;
    body.dataset.segment = segment;
    try {
      const url = panel.dataset.fragmentUrl.replace("{segment}", segment);
      const response = await fetch(url, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error(response.statusText);
      }
      const html = await response.text();
      if (body.dataset.segment === segment) {
        body.innerHTML = html;
        loaded.set(key, "done");
      }
    } catch {
      body.textContent = labels.labelLoadError;
      loaded.delete(key);
    } finally {
      body.removeAttribute("aria-busy");
    }
  }

  function forgetSentence(field) {
    const segment = segmentOf(field);
    for (const key of [...loaded.keys()]) {
      if (key.endsWith(`:${segment}`)) {
        loaded.delete(key);
      }
    }
    if (field === activeField) {
      loadTab(currentTab, true);
    }
  }

  if (tabList && tabButtons.length) {
    tabList.hidden = false;
    tabList.addEventListener("click", (event) => {
      const button = event.target.closest("[role=tab]");
      if (button) {
        showTab(button.dataset.tab);
      }
    });
    tabList.addEventListener("keydown", (event) => {
      const index = tabButtons.indexOf(document.activeElement);
      if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      let next = index;
      if (event.key === "ArrowLeft") next = (index - 1 + tabButtons.length) % tabButtons.length;
      if (event.key === "ArrowRight") next = (index + 1) % tabButtons.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabButtons.length - 1;
      showTab(tabButtons[next].dataset.tab, true);
    });
    const stored = readStoredTab();
    showTab(tabButtons.some((button) => button.dataset.tab === stored) ? stored : currentTab);
  }

  for (const field of fields) {
    field.addEventListener("input", (event) => {
      if (event.inputType === "insertText" && event.data === "=") {
        typeMacron(field);
      }
      const state = states.get(field);
      clearTimeout(state.timer);
      state.timer = setTimeout(() => save(field), SAVE_DELAY);
    });
    field.addEventListener("focus", () => activate(field));
    field.addEventListener("blur", () => save(field));
    for (const name of ["select", "keyup", "mouseup"]) {
      field.addEventListener(name, () => followSelection(field));
    }
    field.addEventListener("keydown", (event) => handleKey(field, event));
  }

  // Sentences the filters leave visible, in order.
  function visibleFields() {
    return fields.filter((candidate) => !candidate.closest(".bitext-row").hidden);
  }

  function move(field, step) {
    const shown = visibleFields();
    const next = shown[shown.indexOf(field) + step];
    if (next) {
      next.focus();
      next.closest(".bitext-row").scrollIntoView({ block: "nearest" });
      return true;
    }
    return false;
  }

  // Keyboard shortcuts, as in translation software; « ? » in the toolbar lists them.
  async function handleKey(field, event) {
    if (event.isComposing) {
      return;
    }
    const command = event.ctrlKey || event.metaKey;
    if (event.key === "Enter" && command) {
      event.preventDefault();
      const done = await markStatus(field, event.shiftKey ? "reviewed" : "translated");
      if (done) {
        move(field, 1);
      }
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      if (!move(field, 1)) {
        save(field);
      }
      return;
    }
    if (event.altKey && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      move(field, event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.altKey && event.shiftKey && event.code === "KeyS") {
      event.preventDefault();
      const source = field.closest(".bitext-row").querySelector(".bitext-source");
      field.setRangeText(source.textContent.trim(), field.selectionStart, field.selectionEnd, "end");
      field.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    if (event.key === "Escape") {
      field.blur();
    }
  }

  // Shortcuts that work anywhere on the page: tabs of the panel and the search.
  document.addEventListener("keydown", (event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    const digit = /^Digit([1-9])$/.exec(event.code);
    if (digit && tabButtons[Number(digit[1]) - 1]) {
      event.preventDefault();
      showTab(tabButtons[Number(digit[1]) - 1].dataset.tab);
      return;
    }
    if (event.code === "KeyF" && searchBox) {
      event.preventDefault();
      searchBox.focus();
      searchBox.select();
    }
  });

  // Filters of the sentences, applied at once; the form still works without the script.
  const searchBox = document.querySelector("[data-editor-search]");
  const filterSelect = document.querySelector("[data-editor-filter]");
  const filterCount = document.querySelector("[data-filter-count]");
  const FILTER_TESTS = {
    "a-traduire": (row) => row.dataset.status === "todo",
    brouillons: (row) => row.dataset.status === "draft",
    "non-relues": (row) => ["draft", "translated"].includes(row.dataset.status),
    "source-modifiee": (row) => row.dataset.sourceChanged === "1",
    commentees: (row) => Number(row.dataset.comments || 0) > 0,
    alertes: (row) => Number(row.dataset.alerts || 0) > 0,
  };

  function fold(text) {
    return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
  }

  function applyFilters() {
    const test = FILTER_TESTS[filterSelect ? filterSelect.value : ""];
    const needle = searchBox ? fold(searchBox.value.trim()) : "";
    const rows = [...editor.querySelectorAll(".bitext-row")];
    let shown = 0;
    for (const row of rows) {
      const source = row.querySelector(".bitext-source").textContent;
      const latin = row.querySelector("textarea").value;
      const visible =
        (!test || test(row)) && (!needle || fold(source).includes(needle) || fold(latin).includes(needle));
      row.hidden = !visible;
      shown += visible ? 1 : 0;
    }
    if (filterCount) {
      filterCount.textContent = shown === rows.length ? "" : `${shown} / ${rows.length}`;
    }
  }

  // Filtering at once needs every sentence on the page: a page filtered by the server keeps
  // its form.
  const asked = new URLSearchParams(window.location.search);
  const pageIsFiltered = Boolean(asked.get("filtre") || asked.get("q"));
  if (!pageIsFiltered && (searchBox || filterSelect)) {
    const submit = document.querySelector("[data-filter-submit]");
    if (submit) {
      submit.hidden = true;
    }
    searchBox?.addEventListener("input", applyFilters);
    filterSelect?.addEventListener("change", applyFilters);
    searchBox?.closest("form").addEventListener("submit", (event) => {
      event.preventDefault();
      applyFilters();
    });
  }

  // The buttons keep the focus in the sentence being typed.
  bar.addEventListener("mousedown", (event) => event.preventDefault());
  bar.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-insert]");
    if (!button || !activeField) {
      return;
    }
    activeField.setRangeText(button.dataset.insert, activeField.selectionStart, activeField.selectionEnd, "end");
    activeField.dispatchEvent(new Event("input", { bubbles: true }));
    activeField.focus();
  });

  // A sentence is saved before its justification page opens.
  document.addEventListener("click", async (event) => {
    const link = event.target.closest(".justify-link");
    const field = link && fields.find((candidate) => candidate.dataset.segment === link.dataset.segment);
    if (!field) {
      return;
    }
    event.preventDefault();
    await save(field);
    window.location.assign(link.href);
  });

  editor.addEventListener("submit", () => {
    submitting = true;
  });
  window.addEventListener("beforeunload", (event) => {
    if (!submitting && fields.some((field) => field.value !== states.get(field).saved)) {
      event.preventDefault();
    }
  });

  // Searches in the side panel (corpus, concordance); the results are HTML rendered and
  // escaped by the server.
  for (const search of document.querySelectorAll(".editor-panel .panel-search")) {
    const results = search.parentElement.querySelector(".panel-results");
    if (!results) {
      continue;
    }
    search.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = new URLSearchParams(new FormData(search));
      const url = new URL(search.dataset.fragmentUrl, window.location.href);
      for (const [name, value] of query) {
        url.searchParams.append(name, value);
      }
      results.setAttribute("aria-busy", "true");
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        results.innerHTML = await response.text();
      } catch {
        results.textContent = labels.labelError;
      } finally {
        results.removeAttribute("aria-busy");
      }
    });
  }
})();
