// The section panel works as plain anchors. This only marks the section in view with
// aria-current, opens a collapsed group when its link is followed, keeps the place on the
// Basic / All switch, and folds the floating list on a narrow screen.
(function () {
  "use strict";

  var panel = document.querySelector(".section-panel");
  if (!panel) {
    return;
  }
  var links = Array.prototype.slice.call(panel.querySelectorAll("nav a[href^='#']"));
  var list = panel.querySelector(".section-list");
  var wide = window.matchMedia("(min-width: 64rem)");

  function target(link) {
    return document.getElementById(link.getAttribute("href").slice(1));
  }

  function mark(current) {
    links.forEach(function (link) {
      if (link === current) {
        link.setAttribute("aria-current", "location");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function fold() {
    if (list) {
      list.open = wide.matches;
    }
  }

  function reveal(element) {
    if (element && element.tagName === "DETAILS") {
      element.open = true;
    }
  }

  fold();
  wide.addEventListener("change", fold);

  if (list) {
    // On a wide screen the list is not a toggle: the keyboard must not collapse it.
    list.addEventListener("toggle", function () {
      if (wide.matches && !list.open) {
        list.open = true;
      }
    });
  }

  links.forEach(function (link) {
    link.addEventListener("click", function () {
      reveal(target(link));
      mark(link);
      if (!wide.matches && list) {
        list.open = false;
      }
    });
  });

  if (window.location.hash) {
    reveal(document.getElementById(window.location.hash.slice(1)));
  }

  panel.querySelectorAll("form.view-switch").forEach(function (form) {
    form.addEventListener("submit", function () {
      var next = form.querySelector("input[name='next']");
      if (next && next.value && next.value.indexOf("#") === -1 && window.location.hash) {
        next.value += window.location.hash;
      }
    });
  });

  // The section in view is the last one whose top has passed the upper third of the window.
  var waiting = false;
  function follow() {
    waiting = false;
    var line = window.innerHeight / 3;
    var current = links[0];
    links.forEach(function (link) {
      var element = target(link);
      if (element && element.getBoundingClientRect().top <= line) {
        current = link;
      }
    });
    if (current) {
      mark(current);
    }
  }
  window.addEventListener(
    "scroll",
    function () {
      if (!waiting) {
        waiting = true;
        window.requestAnimationFrame(follow);
      }
    },
    { passive: true }
  );
  follow();
})();
