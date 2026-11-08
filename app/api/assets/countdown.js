// Shows the time the server says is left, and sends the answers shortly before it ends.
// The server decides whether they arrived in time; nothing here is trusted.
(function () {
  "use strict";

  var SEND_BEFORE_SECONDS = 5;
  var ASK_EVERY_MS = 30000;
  var RETRY_MS = 2000;
  var RETRIES = 3;
  var ANNOUNCE = [
    [300, "five"],
    [60, "one"],
  ];
  var running = null;

  function pad(number) {
    return (number < 10 ? "0" : "") + number;
  }

  function format(seconds) {
    var hours = Math.floor(seconds / 3600);
    var minutes = Math.floor((seconds % 3600) / 60);
    var rest = seconds % 60;
    return (hours ? hours + ":" + pad(minutes) : minutes + "") + ":" + pad(rest);
  }

  function formOf(box) {
    return box.closest("#play").querySelector("form[data-flow]");
  }

  function setEnd(state, seconds) {
    state.end = performance.now() + seconds * 1000;
  }

  function left(state) {
    return Math.max(0, Math.ceil((state.end - performance.now()) / 1000));
  }

  function send(state) {
    if (state.sent) {
      return;
    }
    state.sent = true;
    var form = formOf(state.box);
    if (!form) {
      return;
    }
    var marker = document.createElement("input");
    marker.type = "hidden";
    marker.name = "auto_submit";
    marker.value = "1";
    form.appendChild(marker);
    form.noValidate = true;
    state.box.querySelector("[data-countdown-announce]").textContent = state.box.dataset.sending;
    form.requestSubmit();
  }

  function tick(state) {
    var seconds = left(state);
    state.box.querySelector("[data-countdown-value]").textContent = format(seconds);
    ANNOUNCE.forEach(function (item) {
      if (seconds <= item[0] && state.seen[item[0]] === undefined) {
        state.seen[item[0]] = true;
        if (seconds > item[0] - 5) {
          state.box.querySelector("[data-countdown-announce]").textContent =
            state.box.dataset[item[1]];
        }
      }
    });
    if (seconds <= SEND_BEFORE_SECONDS) {
      send(state);
    }
  }

  function ask(state) {
    var url = state.box.dataset.timeUrl;
    var form = formOf(state.box);
    if (!url || !form || state.sent) {
      return;
    }
    var token = form.querySelector('[name="attempt_token"]');
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "attempt_token=" + encodeURIComponent(token ? token.value : ""),
    })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && typeof data.remaining === "number" && running === state) {
          setEnd(state, data.remaining);
          tick(state);
        }
      })
      .catch(function () {
        // The count keeps running on what it knows; the next question may reach the server.
      });
  }

  function stop() {
    if (running) {
      clearInterval(running.ticking);
      clearInterval(running.asking);
      running = null;
    }
  }

  function setup() {
    var box = document.getElementById("countdown");
    if (running && running.box === box) {
      return;
    }
    stop();
    if (!box) {
      return;
    }
    var state = { box: box, sent: false, seen: {}, retries: 0 };
    setEnd(state, Number(box.dataset.remaining));
    running = state;
    tick(state);
    state.ticking = setInterval(function () {
      tick(state);
    }, 1000);
    state.asking = setInterval(function () {
      ask(state);
    }, ASK_EVERY_MS);
  }

  // A sleeping tab's timers stop, so it asks again as soon as it is seen.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && running) {
      ask(running);
    }
  });

  // The automatic submission must not die on one lost connection. The same key stores once.
  document.addEventListener("htmx:sendError", function () {
    var state = running;
    if (!state || !state.sent || state.retries >= RETRIES) {
      return;
    }
    state.retries += 1;
    setTimeout(function () {
      var form = formOf(state.box);
      if (form && running === state) {
        form.requestSubmit();
      }
    }, RETRY_MS);
  });

  document.addEventListener("DOMContentLoaded", setup);
  document.addEventListener("htmx:afterSwap", setup);
})();
