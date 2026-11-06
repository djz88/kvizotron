// HTMX shows nothing when the network fails, so a participant would see a dead button.
(function () {
  "use strict";

  function showNetworkError() {
    var message = document.getElementById("play-message");
    if (message) {
      message.textContent = message.dataset.networkError;
    }
  }

  document.addEventListener("htmx:sendError", showNetworkError);
  document.addEventListener("htmx:responseError", showNetworkError);
  document.addEventListener("htmx:beforeRequest", function () {
    var message = document.getElementById("play-message");
    if (message) {
      message.textContent = "";
    }
  });
})();
