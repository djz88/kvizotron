// HTMX shows nothing when the network fails, so a participant would see a dead button.
(function () {
  "use strict";

  function showNetworkError(event) {
    var message = document.getElementById("play-message");
    if (message) {
      var tooLarge = event.detail && event.detail.xhr && event.detail.xhr.status === 413;
      message.textContent = tooLarge ? message.dataset.tooLarge : message.dataset.networkError;
    }
  }

  // The private result link, remembered per quiz on this device. Private browsing may refuse it.
  function remember(root) {
    root.querySelectorAll("[data-result-quiz]").forEach(function (element) {
      try {
        localStorage.setItem(
          "kvz-result-" + element.dataset.resultQuiz,
          element.dataset.resultLink
        );
      } catch (error) {
        return;
      }
    });
  }

  function fillSlots() {
    document.querySelectorAll("[data-result-slot]").forEach(function (slot) {
      var link = null;
      try {
        link = localStorage.getItem("kvz-result-" + slot.dataset.resultSlot);
      } catch (error) {
        return;
      }
      if (link && link.indexOf("/v/") === 0) {
        slot.querySelector("a").href = link;
        slot.hidden = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    remember(document);
    fillSlots();
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    remember(event.target);
  });
  document.addEventListener("htmx:sendError", showNetworkError);
  document.addEventListener("htmx:responseError", showNetworkError);
  document.addEventListener("htmx:beforeRequest", function () {
    var message = document.getElementById("play-message");
    if (message) {
      message.textContent = "";
    }
  });
})();
