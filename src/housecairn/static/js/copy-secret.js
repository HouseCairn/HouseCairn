// Copy button of a secret shown once. Hidden until this script runs and the browser can copy.
(function () {
  "use strict";
  var buttons = document.querySelectorAll("button[data-copy-from]");
  Array.prototype.forEach.call(buttons, function (button) {
    var source = document.getElementById(button.getAttribute("data-copy-from"));
    if (!source || !navigator.clipboard || !navigator.clipboard.writeText) {
      return;
    }
    button.hidden = false;
    var label = button.textContent;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(source.value).then(function () {
        button.textContent = button.getAttribute("data-copied") || label;
        window.setTimeout(function () {
          button.textContent = label;
        }, 2000);
      });
      source.select();
    });
  });
})();
