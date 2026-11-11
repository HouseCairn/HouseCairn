// The summary of the errors of a form (templates/components/form_errors.html, design guide,
// "Forms"). Without script the summary already takes the focus (`autofocus`) and each line
// links to its field. With script, three things more, none of them needed to read the errors:
// a folded section that holds a field in error is opened, a click on a line puts the focus in
// the field and not only the page next to it, and a summary that arrives in an HTMX response
// takes the focus as well. First-party, no library.
(function () {
  "use strict";

  function openSections(root) {
    root.querySelectorAll("[aria-invalid=true]").forEach(function (field) {
      var section = field.closest("details");
      while (section) {
        section.open = true;
        section = section.parentElement ? section.parentElement.closest("details") : null;
      }
    });
  }

  function focusSummary(root) {
    var summary = root.querySelector("[data-form-errors]");
    if (summary) {
      summary.focus();
    }
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest("[data-form-errors] a[href^='#']") : null;
    if (!link) {
      return;
    }
    var field = document.getElementById(link.getAttribute("href").slice(1));
    if (field) {
      event.preventDefault();
      openSections(document);
      field.focus();
      field.scrollIntoView({ block: "center" });
    }
  });

  document.addEventListener("htmx:afterSettle", function (event) {
    var target = event.target && event.target.querySelector ? event.target : document;
    openSections(target);
    focusSummary(target);
  });

  openSections(document);
})();
