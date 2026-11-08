// One question, or one page of questions, at a time.
// Without this script the same form shows them all on one page.
(function () {
  "use strict";

  function setProgress(form, text, current, total, first) {
    var box = form.querySelector(".flow-progress");
    if (!box) {
      return;
    }
    box.hidden = false;
    box.querySelector("span").textContent = text
      .replace("{current}", current)
      .replace("{first}", first === undefined ? current : first)
      .replace("{last}", current)
      .replace("{total}", total);
    var bar = box.querySelector("progress");
    bar.max = total;
    bar.value = current;
  }

  function hasAnswer(section) {
    return Array.prototype.some.call(section.querySelectorAll("input, select"), function (field) {
      if (field.type === "radio" || field.type === "checkbox") {
        return field.checked;
      }
      return field.tagName === "SELECT" && field.value !== "";
    });
  }

  function setupAllAtOnce(form, sections) {
    var answered = sections.filter(hasAnswer);
    var show = function () {
      setProgress(form, form.dataset.progressAll, answered.length, sections.length);
    };
    form.addEventListener("change", function (event) {
      var section = event.target.closest(".flow-question");
      if (!section) {
        return;
      }
      var position = answered.indexOf(section);
      // Moving an item is an answer, and unticking the last box takes one back.
      var isAnswered = hasAnswer(section) || section.querySelector("[data-sortable]");
      if (isAnswered && position === -1) {
        answered.push(section);
      } else if (!isAnswered && position !== -1) {
        answered.splice(position, 1);
      }
      show();
    });
    show();
  }

  // A disabled field is not sent, and the checked answer still counts, so a copy goes instead.
  function lock(section) {
    section.classList.add("flow-locked");
    section.querySelectorAll("input, select, button").forEach(function (field) {
      if (field.type === "hidden" || field.disabled) {
        return;
      }
      var sent = field.tagName !== "BUTTON" && (field.tagName === "SELECT" || field.checked);
      if (sent) {
        var copy = document.createElement("input");
        copy.type = "hidden";
        copy.name = field.name;
        copy.value = field.value;
        section.appendChild(copy);
      }
      field.disabled = true;
    });
    var check = section.querySelector("[data-flow-check-button]");
    if (check) {
      check.hidden = true;
    }
    section.querySelector(".flow-reveal").focus();
  }

  function setupChecks(form, sections) {
    sections.forEach(function (section) {
      var button = section.querySelector("[data-flow-check-button]");
      button.hidden = false;
      // Any order is an answer, so an ordering question can be checked straight away.
      button.disabled = !hasAnswer(section) && !section.querySelector("[data-sortable]");
    });
    form.addEventListener("change", function (event) {
      var section = event.target.closest(".flow-question");
      var button = section && section.querySelector("[data-flow-check-button]");
      if (button && !section.classList.contains("flow-locked")) {
        button.disabled = false;
      }
    });
    form.addEventListener("htmx:afterSwap", function (event) {
      if (event.target.classList.contains("flow-reveal")) {
        lock(event.target.closest(".flow-question"));
      }
    });
  }

  function setupSteps(form, sections) {
    var nav = form.querySelector(".flow-nav");
    var previous = nav.querySelector("[data-flow-previous]");
    var next = nav.querySelector("[data-flow-next]");
    var submit = form.querySelector("#play-submit");
    var size = Math.max(Number(form.dataset.flowPage) || 1, 1);
    var steps = Math.ceil(sections.length / size);
    var current = 0;

    function show(index, moveFocus) {
      current = index;
      var first = index * size;
      var end = Math.min(first + size, sections.length);
      sections.forEach(function (section, position) {
        section.hidden = position < first || position >= end;
      });
      var last = index === steps - 1;
      previous.hidden = index === 0 || !("flowBack" in form.dataset);
      next.hidden = last;
      submit.hidden = !last;
      var identity = form.querySelector("[data-identity-fields]");
      if (identity) {
        identity.hidden = !last;
      }
      if (size > 1) {
        setProgress(form, form.dataset.progressPage, end, sections.length, first + 1);
      } else {
        setProgress(form, form.dataset.progressStep, index + 1, sections.length);
      }
      // The index is the step: a question, or a page of them, which resume.js restores.
      form.dispatchEvent(new CustomEvent("kvz:step", { bubbles: true, detail: { index: index } }));
      if (moveFocus) {
        sections[first].focus();
      }
    }

    next.addEventListener("click", function () {
      show(current + 1, true);
    });
    previous.addEventListener("click", function () {
      show(current - 1, true);
    });
    // A restored attempt goes back to the question it was left on.
    form.addEventListener("kvz:goto", function (event) {
      var index = Math.min(Math.max(Number(event.detail.index) || 0, 0), steps - 1);
      show(index, false);
    });
    // Enter in a field would submit the whole quiz from the middle of it.
    form.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && event.target.tagName === "INPUT") {
        event.preventDefault();
      }
    });
    nav.hidden = false;
    show(0, false);
    if ("flowCheck" in form.dataset) {
      setupChecks(form, sections);
    }
  }

  function setup() {
    var form = document.querySelector("form[data-flow]");
    if (!form || form.dataset.flowReady) {
      return;
    }
    var sections = Array.prototype.slice.call(form.querySelectorAll(".flow-question"));
    if (!sections.length) {
      return;
    }
    form.dataset.flowReady = "1";
    if ("flowStep" in form.dataset) {
      setupSteps(form, sections);
    } else {
      setupAllAtOnce(form, sections);
    }
  }

  document.addEventListener("DOMContentLoaded", setup);
  document.addEventListener("htmx:afterSwap", setup);
})();
