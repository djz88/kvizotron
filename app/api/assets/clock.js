// Puts the browser's clock next to the server's, so a difference is seen before it matters.
(function () {
  "use strict";

  var ALLOWED_SECONDS = 60;

  // Both lines in the browser's own regional format, so they compare at a glance.
  function local(date, zone) {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    }).format(date);
  }

  function setup() {
    var box = document.getElementById("clock");
    if (!box) {
      return;
    }
    var now = new Date();
    var zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    box.querySelector("[data-browser-time]").textContent = local(now, zone);
    try {
      box.querySelector("[data-server-time]").textContent = local(
        new Date(Number(box.dataset.serverEpoch) * 1000),
        box.dataset.serverZone
      );
    } catch (error) {
      // A zone the browser does not know keeps the server's own wording.
    }
    box.querySelector("[data-browser-zone]").textContent = "(" + zone + ")";
    box.querySelector("[data-browser]").hidden = false;
    var warnings = [];
    if (Math.abs(now.getTime() / 1000 - Number(box.dataset.serverEpoch)) > ALLOWED_SECONDS) {
      warnings.push(box.dataset.warnClock);
    }
    if (zone !== box.dataset.zone) {
      warnings.push(box.dataset.warnZone);
    }
    if (box.dataset.serverZone !== box.dataset.zone) {
      warnings.push(box.dataset.warnServerZone);
    }
    var warning = box.querySelector("[data-warning]");
    warning.textContent = warnings.join(" ");
    warning.hidden = warnings.length === 0;
  }

  document.addEventListener("DOMContentLoaded", setup);
})();
