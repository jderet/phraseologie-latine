// Translation editor: saves each sentence when it is left, types macrons, searches the corpus
// and prepares justifications. Without this script the page still works: the form saves every
// sentence at once, and justifications are reached from the page of the version.
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
    field.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
        return;
      }
      event.preventDefault();
      const next = fields[fields.indexOf(field) + 1];
      if (next) {
        next.focus();
      } else {
        save(field);
      }
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

  // Corpus search in the side panel; the results are HTML rendered and escaped by the server.
  const search = document.querySelector(".editor-panel .panel-search");
  const results = document.querySelector(".panel-results");
  if (search && results) {
    search.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = new URLSearchParams(new FormData(search));
      results.setAttribute("aria-busy", "true");
      try {
        const response = await fetch(`${search.dataset.fragmentUrl}?${query}`, { credentials: "same-origin" });
        results.innerHTML = await response.text();
      } catch {
        results.textContent = labels.labelError;
      } finally {
        results.removeAttribute("aria-busy");
      }
    });
  }
})();
