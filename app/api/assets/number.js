// Warns, under a number field, that a comma or dot with exactly three digits after it is a
// decimal sign ("1,000" is one, "2,500" is 2.5). It only writes a note: sending is never blocked
// and the server reads the field as before.
(function () {
  "use strict";

  // An optional minus sign, one to three digits, one separator and exactly three digits.
  var THOUSANDS = /^-?\d{1,3}[.,]\d{3}$/;

  // The note is a live region that stays in the page; its text is written and cleared, which
  // screen readers announce, unlike taking `hidden` off.
  function update(note) {
    var fieldset = note.closest("fieldset");
    var input = fieldset ? fieldset.querySelector('input[type="text"]') : null;
    var text = input ? input.value.trim() : "";
    if (!THOUSANDS.test(text)) {
      note.textContent = "";
      return;
    }
    // The reading is the decimal the server makes of it: 1,000 is 1 and 2,500 is 2.5. It is
    // written with the separator the participant typed, so 2,500 reads as 2,5.
    var read = String(parseFloat(text.replace(",", ".")));
    if (text.indexOf(",") !== -1) {
      read = read.replace(".", ",");
    }
    note.textContent = note.dataset.text.replace("{value}", text).replace("{read}", read);
  }

  function updateAll() {
    document.querySelectorAll("[data-number-note]").forEach(update);
  }

  document.addEventListener("input", function (event) {
    var fieldset = event.target.closest ? event.target.closest("fieldset") : null;
    var note = fieldset ? fieldset.querySelector("[data-number-note]") : null;
    if (note) {
      update(note);
    }
  });

  // The field may be filled again by resume.js, so the notes are read once the page is there and
  // after every swap.
  document.addEventListener("DOMContentLoaded", updateAll);
  document.addEventListener("htmx:afterSwap", updateAll);
})();
