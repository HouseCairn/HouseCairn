// The task form hides the fields its choices do not use (docs/screens/task-form.md).
// First-party, no library. An element with `data-shown-when="name"` shows while the box
// `name` is ticked; with `data-shown-when="name=value"`, while the field `name` has that
// value. Without script nothing is hidden, and the server ignores what is not used.
// The due date has two fields (the first block, and the date a fixed repetition counts
// from): typing in one fills in the other.
(function () {
  "use strict";
  var form = document.querySelector("form[data-task-form]");
  if (!form) {
    return;
  }
  var rules = form.querySelectorAll("[data-shown-when]");

  function value(name) {
    var field = form.elements.namedItem(name);
    if (!field) {
      return "";
    }
    if (field.type === "checkbox") {
      return field.checked ? "on" : "";
    }
    return field.value || "";
  }

  function update() {
    rules.forEach(function (element) {
      var rule = element.getAttribute("data-shown-when").split("=");
      var current = value(rule[0]);
      element.hidden = rule.length > 1 ? current !== rule[1] : current === "";
    });
  }

  function mirror(source, target) {
    source.addEventListener("input", function () {
      if (target.value !== source.value) {
        target.value = source.value;
      }
    });
  }

  var due = form.elements.namedItem("due_on");
  var start = form.elements.namedItem("repeat_start");
  if (due && start) {
    mirror(due, start);
    mirror(start, due);
  }
  form.addEventListener("change", update);
  update();
})();
