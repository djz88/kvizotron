// Small helps for forms; everything still works without this script.
(function () {
  "use strict";

  // Leaving a changed form asks first. Saving does not.
  function state(form) {
    var values = new URLSearchParams(new FormData(form)).toString();
    var files = Array.prototype.map.call(form.querySelectorAll('input[type="file"]'), function (input) {
      return input.files.length;
    });
    return values + "|" + files.join(",");
  }

  var forms = Array.prototype.map.call(document.querySelectorAll("form.watch-changes"), function (form) {
    return { form: form, initial: state(form) };
  });

  window.addEventListener("beforeunload", function (event) {
    var changed = forms.some(function (entry) {
      return !entry.saving && state(entry.form) !== entry.initial;
    });
    if (changed) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    forms.forEach(function (entry) {
      entry.saving = true;
    });
    if (form.classList.contains("watch-changes")) {
      var button = form.querySelector('button[type="submit"]');
      if (button) {
        // Later, so that the browser still sends the form.
        window.setTimeout(function () {
          button.disabled = true;
        });
      }
    }
  });

  // Coming back through the browser history shows the form as it was left.
  window.addEventListener("pageshow", function () {
    forms.forEach(function (entry) {
      entry.saving = false;
      entry.form.querySelectorAll('button[type="submit"]').forEach(function (button) {
        button.disabled = false;
      });
    });
  });

  // An option chosen in one row of a pair question is greyed out in the others.
  function refreshChoices(fieldset) {
    var selects = fieldset.querySelectorAll("select");
    selects.forEach(function (select) {
      select.querySelectorAll("option").forEach(function (option) {
        option.disabled = option.value !== "" && Array.prototype.some.call(selects, function (other) {
          return other !== select && other.value === option.value;
        });
      });
    });
  }

  function refreshAllChoices() {
    document.querySelectorAll("[data-unique-choices]").forEach(refreshChoices);
  }

  document.addEventListener("change", function (event) {
    var fieldset = event.target.closest("[data-unique-choices]");
    if (fieldset) {
      refreshChoices(fieldset);
    }
  });
  document.addEventListener("htmx:afterSwap", refreshAllChoices);
  refreshAllChoices();

  // "None of the answers" and the other answers exclude each other.
  document.addEventListener("change", function (event) {
    var input = event.target;
    if (input.type !== "checkbox" || !input.checked) {
      return;
    }
    var fieldset = input.closest("fieldset");
    if (!fieldset || !fieldset.querySelector("[data-none]")) {
      return;
    }
    fieldset.querySelectorAll('input[type="checkbox"]').forEach(function (other) {
      if (other !== input && (input.hasAttribute("data-none") || other.hasAttribute("data-none"))) {
        other.checked = false;
      }
    });
  });
})();
