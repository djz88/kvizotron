// Shows the time the server says is left, and sends the answers shortly before it ends.
// The server decides whether they arrived in time; nothing here is trusted.
(function () {
  "use strict";

  var SEND_BEFORE_SECONDS = 5;
  var ASK_EVERY_MS = 30000;
  // Waits before each repeat after a lost connection or a 5xx (six repeats at most).
  // The server refuses any send after the limit, so the first three repeats fall inside the
  // margin before it (1 + 1 + 1.5 s); the later ones only fetch the server's verdict.
  var REPEAT_MS = [1000, 1000, 1500, 3000, 6000, 12000];
  // A 429 waits what Retry-After says (seconds, capped), and only twice in all.
  var LIMITED_TIMES = 2;
  var LIMITED_MAX_SECONDS = 60;
  var LIMITED_DEFAULT_SECONDS = 60;
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
    var play = box.closest("#play");
    return play ? play.querySelector("form[data-flow]") : null;
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
      clearTimeout(running.waiting);
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
    var state = { box: box, sent: false, seen: {}, repeats: 0, limited: 0, waiting: null };
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

  // The note is a live region that stays in the page; its text is written and cleared, which
  // screen readers announce, unlike taking `hidden` off.
  function showNote(state, shown) {
    var note = state.box.querySelector("[data-countdown-retry]");
    if (note) {
      note.textContent = shown ? note.dataset.text : "";
    }
  }

  // The answer arrived, or there is nothing more to try: the note goes and no repeat is waiting.
  function settle(state) {
    clearTimeout(state.waiting);
    state.waiting = null;
    showNote(state, false);
  }

  // Every repeat is the same requestSubmit() as the first send, so the submission key is reused
  // and the server stores the answers once.
  function repeatIn(state, wait) {
    clearTimeout(state.waiting);
    showNote(state, true);
    state.waiting = setTimeout(function () {
      var form = formOf(state.box);
      if (form && running === state) {
        form.requestSubmit();
      }
    }, wait);
  }

  function repeatAfterFailure(state) {
    if (state.repeats >= REPEAT_MS.length) {
      settle(state);
      return;
    }
    var wait = REPEAT_MS[state.repeats];
    state.repeats += 1;
    repeatIn(state, wait);
  }

  function repeatAfterLimit(state, xhr) {
    if (state.limited >= LIMITED_TIMES) {
      settle(state);
      return;
    }
    state.limited += 1;
    var seconds = parseInt(xhr.getResponseHeader("Retry-After"), 10);
    if (isNaN(seconds)) {
      seconds = LIMITED_DEFAULT_SECONDS;
    }
    repeatIn(state, Math.min(Math.max(seconds, 1), LIMITED_MAX_SECONDS) * 1000);
  }

  // The state of the automatic submission this htmx event is about, or null: it must have begun
  // and the event must come from this page's form.
  function pending(event) {
    var state = running;
    if (!state || !state.sent) {
      return null;
    }
    var form = formOf(state.box);
    return form && event.target === form ? state : null;
  }

  // A lost connection. There is no request timeout: cutting a request the server may still be
  // storing would make the repeat late while the first send commits.
  function onLost(event) {
    var state = pending(event);
    if (state) {
      repeatAfterFailure(state);
    }
  }

  document.addEventListener("htmx:sendError", onLost);

  // htmx raises this only for a 5xx (the response handling in rendering.py): a 4xx is swapped
  // as a message, so a 429 is read in afterRequest below.
  document.addEventListener("htmx:responseError", function (event) {
    var state = pending(event);
    if (state && event.detail.xhr.status >= 500) {
      repeatAfterFailure(state);
    }
  });

  // Every request ends here, so this is where a 429 is seen and where any other answer ends the
  // repeating. A lost connection and a 5xx are handled by the listeners above.
  document.addEventListener("htmx:afterRequest", function (event) {
    var state = pending(event);
    if (!state) {
      return;
    }
    var xhr = event.detail.xhr;
    if (xhr.status === 429) {
      repeatAfterLimit(state, xhr);
    } else if (xhr.status > 0 && xhr.status < 500) {
      settle(state);
    }
  });

  document.addEventListener("DOMContentLoaded", setup);
  document.addEventListener("htmx:afterSwap", setup);
})();
