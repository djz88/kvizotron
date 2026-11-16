// Names edited on the spot (AC-160): Esc closes the field, and focus follows the swap.
// Without this script the pencil is a link to a page with the field open and everything works.
(function () {
  "use strict";

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || !event.target.closest) {
      return;
    }
    var form = event.target.closest(".inline-name-form");
    var cancel = form && form.querySelector(".inline-name-cancel");
    if (cancel) {
      event.preventDefault();
      cancel.click();
    }
  });

  // `htmx:load` fires on the element that was swapped in (the old one is gone).
  document.body.addEventListener("htmx:load", function (event) {
    var box = event.target;
    if (!box.matches || !box.matches(".inline-name")) {
      return;
    }
    var next = box.querySelector(".inline-name-form input[type=text]") || box.querySelector(".inline-name-pencil");
    if (next) {
      next.focus();
    }
  });
})();
