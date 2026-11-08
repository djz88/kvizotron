// Brings up the start button for people waiting at the page. It reloads once, without polling,
// and spreads the reloads so that a full room does not arrive in the same instant.
(function () {
  "use strict";

  var SPREAD_MS = 5000;

  function setup() {
    var element = document.querySelector("[data-starts-in]");
    if (!element) {
      return;
    }
    var wait = Number(element.dataset.startsIn) * 1000 + Math.random() * SPREAD_MS;
    setTimeout(function () {
      window.location.reload();
    }, wait);
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
