// Full screen for the projector view of a scoreboard. Without support the button stays hidden.
(function () {
  "use strict";
  var button = document.querySelector("[data-fullscreen]");
  if (!button || !document.documentElement.requestFullscreen) {
    return;
  }
  button.hidden = false;
  button.addEventListener("click", function () {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else {
      document.querySelector(".scoreboard").requestFullscreen();
    }
  });
})();
