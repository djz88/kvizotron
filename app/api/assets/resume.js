// A copy of an unsubmitted attempt is kept in this browser, so a reload does not lose the answers.
// It holds answers and the place in the quiz, never a photo, a name or an e-mail address.
(function () {
  "use strict";

  var SKIPPED = [
    "participant_name",
    "participant_email",
    "attempt_token",
    "submission_key",
    "csrfmiddlewaretoken",
    "lang",
    "check_question",
  ];
  var pending = null;
  var lastRun = null;

  function keyOf(run) {
    return "kvz-attempt-" + run;
  }

  // Private browsing may refuse the storage, and then there is simply no copy.
  function read(run) {
    try {
      var copy = JSON.parse(localStorage.getItem(keyOf(run)));
      var valid =
        copy &&
        typeof copy.attempt === "string" &&
        typeof copy.token === "string" &&
        Date.parse(copy.expires) > Date.now();
      if (!valid) {
        drop(run);
        return null;
      }
      return copy;
    } catch (error) {
      return null;
    }
  }

  function write(run, copy) {
    try {
      localStorage.setItem(keyOf(run), JSON.stringify(copy));
    } catch (error) {
      return;
    }
  }

  function drop(run) {
    try {
      localStorage.removeItem(keyOf(run));
    } catch (error) {
      return;
    }
  }

  // A copy of a run nobody opens again would otherwise stay. Every page load removes the old ones.
  function sweep() {
    try {
      var stale = [];
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (!key || !key.startsWith("kvz-attempt-")) {
          continue;
        }
        var copy = null;
        try {
          copy = JSON.parse(localStorage.getItem(key));
        } catch (error) {
          copy = null;
        }
        if (!copy || typeof copy !== "object" || !(Date.parse(copy.expires) > Date.now())) {
          stale.push(key);
        }
      }
      stale.forEach(function (key) {
        localStorage.removeItem(key);
      });
    } catch (error) {
      return;
    }
  }

  function resumable() {
    return document.querySelector("form[data-local-resume]");
  }

  function inOrderList(field) {
    return field.tagName === "SELECT" && field.closest("[data-sortable] li");
  }

  function collect(form) {
    var answers = {};
    Array.prototype.forEach.call(form.elements, function (field) {
      var name = field.name;
      if (!name || SKIPPED.indexOf(name) !== -1 || field.type === "file" || field.type === "submit") {
        return;
      }
      if (field.tagName === "BUTTON" || inOrderList(field)) {
        return;
      }
      if ((field.type === "radio" || field.type === "checkbox") && !field.checked) {
        return;
      }
      if (field.value === "") {
        return;
      }
      (answers[name] = answers[name] || []).push(field.value);
    });
    Object.keys(answers).forEach(function (name) {
      if (answers[name].length === 1) {
        answers[name] = answers[name][0];
      }
    });
    return answers;
  }

  function save(form) {
    var token = form.querySelector('input[name="attempt_token"]');
    if (!token) {
      return;
    }
    lastRun = form.dataset.run;
    write(form.dataset.run, {
      attempt: form.dataset.attempt,
      token: token.value,
      expires: form.dataset.copyExpires,
      step: Number(form.dataset.step || 0),
      answers: collect(form),
    });
  }

  function named(form, name) {
    return Array.prototype.filter.call(form.elements, function (field) {
      return field.name === name;
    });
  }

  function restoreOrder(form, name, values) {
    var list = Array.prototype.find.call(form.querySelectorAll("[data-sortable]"), function (one) {
      return one.dataset.name === name;
    });
    if (!list) {
      return false;
    }
    var holder = list.nextElementSibling;
    var byId = {};
    Array.prototype.forEach.call(list.children, function (item) {
      byId[item.dataset.id] = item;
    });
    var known = values.filter(function (id) {
      return byId[id];
    });
    if (!known.length || !holder) {
      return true;
    }
    holder.textContent = "";
    known.forEach(function (id) {
      list.appendChild(byId[id]);
    });
    Array.prototype.forEach.call(list.children, function (item) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = item.dataset.id;
      holder.appendChild(input);
    });
    list.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function setField(field, values) {
    var changed = false;
    if (field.type === "radio" || field.type === "checkbox") {
      var wanted = values.indexOf(field.value) !== -1;
      changed = field.checked !== wanted;
      field.checked = wanted;
    } else if (field.tagName === "SELECT") {
      var known = Array.prototype.some.call(field.options, function (option) {
        return option.value === values[0];
      });
      if (known && field.value !== values[0]) {
        field.value = values[0];
        changed = true;
      }
    } else if (field.type !== "hidden" && field.type !== "file") {
      if (field.value !== values[0]) {
        field.value = values[0];
        changed = true;
      }
    }
    if (changed) {
      field.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function restore(form, copy) {
    var answers = copy.answers && typeof copy.answers === "object" ? copy.answers : {};
    Object.keys(answers).forEach(function (name) {
      if (SKIPPED.indexOf(name) !== -1) {
        return;
      }
      var values = [].concat(answers[name]).map(String);
      if (restoreOrder(form, name, values)) {
        return;
      }
      named(form, name).forEach(function (field) {
        if (field.type !== "hidden") {
          setField(field, values);
        }
      });
    });
    form.querySelectorAll('input[type="file"]').forEach(function (input) {
      var note = document.createElement("small");
      note.dataset.photoNoteShown = "1";
      note.textContent = form.dataset.photoNote;
      input.insertAdjacentElement("afterend", note);
    });
    var step = Number(copy.step);
    if (step > 0) {
      form.dispatchEvent(new CustomEvent("kvz:goto", { bubbles: true, detail: { index: step } }));
    }
  }

  function showOffers() {
    document.querySelectorAll("[data-resume-offer]").forEach(function (offer) {
      var copy = read(offer.dataset.run);
      if (!copy) {
        return;
      }
      offer.querySelector('input[name="attempt_id"]').value = copy.attempt;
      offer.querySelector('input[name="attempt_token"]').value = copy.token;
      offer.hidden = false;
      var start = document.querySelector("[data-start-form]");
      if (start) {
        start.hidden = true;
      }
    });
  }

  function showStart() {
    document.querySelectorAll("[data-resume-offer]").forEach(function (offer) {
      offer.hidden = true;
    });
    var start = document.querySelector("[data-start-form]");
    if (start) {
      start.hidden = false;
    }
  }

  function runOf(event) {
    var path = (event.detail && event.detail.pathInfo && event.detail.pathInfo.requestPath) || "";
    var found = /\/r\/([0-9a-f-]+)\/resume$/.exec(path);
    return found ? found[1] : null;
  }

  document.addEventListener("DOMContentLoaded", function () {
    sweep();
    showOffers();
  });

  document.addEventListener("click", function (event) {
    var restart = event.target.closest && event.target.closest("[data-resume-restart]");
    if (restart) {
      drop(restart.closest("[data-resume-offer]").dataset.run);
      showStart();
    }
  });

  document.addEventListener("htmx:beforeRequest", function (event) {
    var offer = event.target.closest && event.target.closest("[data-resume-offer]");
    pending = offer ? read(offer.dataset.run) : null;
  });

  document.addEventListener("htmx:afterSwap", function () {
    var form = resumable();
    if (!form) {
      return;
    }
    if (pending) {
      var copy = pending;
      pending = null;
      restore(form, copy);
    }
    save(form);
  });

  document.addEventListener("htmx:afterRequest", function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr) {
      return;
    }
    var path = (event.detail.pathInfo && event.detail.pathInfo.requestPath) || "";
    var ran = runOf(event);
    if (ran && (xhr.status === 404 || xhr.getResponseHeader("X-Kvz-Drop-Copy"))) {
      drop(ran);
      showStart();
    } else if (xhr.getResponseHeader("X-Kvz-Drop-Copy") && lastRun) {
      drop(lastRun);
    } else if (/\/submit$/.test(path) && xhr.status === 200 && !resumable() && lastRun) {
      // The questions are gone from the page, so the answers went in.
      drop(lastRun);
    }
  });

  document.addEventListener("change", function (event) {
    var form = event.target.closest && event.target.closest("form[data-local-resume]");
    if (form) {
      save(form);
    }
  });

  document.addEventListener("kvz:step", function (event) {
    var form = event.target.closest && event.target.closest("form[data-local-resume]");
    if (form) {
      form.dataset.step = String(event.detail.index);
      save(form);
    }
  });
})();
