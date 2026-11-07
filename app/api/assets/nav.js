// Menus are <details open>, so everything is reachable without JavaScript.
// On a narrow screen they start closed; on a wide one their button is hidden and they stay open.
(function () {
  "use strict";

  var narrow = window.matchMedia("(max-width: 48rem)");

  document.documentElement.classList.add("js");

  function apply() {
    document.querySelectorAll(".site-nav, .quiz-fold").forEach(function (fold) {
      fold.open = !narrow.matches;
    });
  }

  apply();
  narrow.addEventListener("change", apply);
})();
