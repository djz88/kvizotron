// Ordering by drag and drop (mouse and touch) and by buttons (keyboard). Without this script the
// list keeps a position dropdown for each item. Listeners are delegated, so swaps need no rebinding.
(function () {
  "use strict";

  var dragged = null;

  function items(list) {
    return Array.prototype.filter.call(list.children, function (child) {
      return child.tagName === "LI";
    });
  }

  function chosenPosition(item) {
    var select = item.querySelector("select");
    return select && select.value ? Number(select.value) : Infinity;
  }

  function button(label, direction) {
    var element = document.createElement("button");
    element.type = "button";
    element.className = "sortable-move secondary outline";
    element.textContent = direction === "up" ? "↑" : "↓";
    element.setAttribute("aria-label", label);
    element.dataset.move = direction;
    return element;
  }

  function writeOrder(list) {
    var holder = list.nextElementSibling;
    holder.textContent = "";
    items(list).forEach(function (item) {
      var input = document.createElement("input");
      input.type = "hidden";
      input.name = list.dataset.name;
      input.value = item.dataset.id;
      holder.appendChild(input);
    });
  }

  // The order lives in hidden inputs, which fire nothing, and other scripts want to know.
  function announce(list) {
    writeOrder(list);
    list.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setUp(list) {
    if (list.dataset.sortableReady) {
      return;
    }
    list.dataset.sortableReady = "1";
    items(list)
      .map(function (item, index) {
        return { item: item, index: index, position: chosenPosition(item) };
      })
      .sort(function (a, b) {
        return a.position - b.position || a.index - b.index;
      })
      .forEach(function (entry) {
        list.appendChild(entry.item);
      });
    items(list).forEach(function (item) {
      item.querySelector("select").remove();
      var handle = document.createElement("span");
      handle.className = "sortable-handle";
      handle.setAttribute("aria-hidden", "true");
      handle.textContent = "☰";
      item.insertBefore(handle, item.firstChild);
      item.appendChild(button(list.dataset.up, "up"));
      item.appendChild(button(list.dataset.down, "down"));
    });
    var holder = document.createElement("div");
    holder.hidden = true;
    list.after(holder);
    var status = document.createElement("p");
    status.className = "sr-only";
    status.setAttribute("role", "status");
    holder.after(status);
    var note = status.parentElement.querySelector(".sortable-note");
    if (note) {
      note.remove();
    }
    writeOrder(list);
  }

  function setUpAll() {
    document.querySelectorAll("[data-sortable]").forEach(setUp);
  }

  function move(control) {
    var item = control.closest("li");
    var list = item.parentElement;
    var up = control.dataset.move === "up";
    var other = up ? item.previousElementSibling : item.nextElementSibling;
    if (!other) {
      return;
    }
    list.insertBefore(up ? item : other, up ? other : item);
    announce(list);
    control.focus();
    var position = items(list).indexOf(item) + 1;
    list.nextElementSibling.nextElementSibling.textContent = list.dataset.moved.replace("{n}", position);
  }

  document.addEventListener("click", function (event) {
    var control = event.target.closest("[data-move]");
    if (control) {
      event.preventDefault();
      move(control);
    }
  });

  document.addEventListener("pointerdown", function (event) {
    var handle = event.target.closest(".sortable-handle");
    if (handle) {
      event.preventDefault();
      dragged = handle.closest("li");
      dragged.classList.add("sortable-dragged");
    }
  });

  document.addEventListener("pointermove", function (event) {
    if (!dragged) {
      return;
    }
    var list = dragged.parentElement;
    var next = items(list).find(function (item) {
      var box = item.getBoundingClientRect();
      return item !== dragged && event.clientY < box.top + box.height / 2;
    });
    list.insertBefore(dragged, next || null);
  });

  function drop() {
    if (dragged) {
      dragged.classList.remove("sortable-dragged");
      announce(dragged.parentElement);
      dragged = null;
    }
  }

  document.addEventListener("pointerup", drop);
  document.addEventListener("pointercancel", drop);
  document.addEventListener("htmx:afterSwap", setUpAll);
  setUpAll();
})();
