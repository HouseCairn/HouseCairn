// Calendar: with the focus inside the calendar, the left and right arrows go to the
// previous and next period and T to today. Only while the focus is in it (WCAG 2.1.4), and
// never while a field is being edited. Every action is also a link: the script adds nothing.
document.addEventListener("DOMContentLoaded", function () {
  var region = document.getElementById("calendar");
  if (!region) return;
  region.addEventListener("keydown", function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    var tag = (event.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "select" || tag === "textarea") return;
    var wanted = { ArrowLeft: "prev", ArrowRight: "next", t: "today", T: "today" }[event.key];
    var link = wanted && region.querySelector('a[data-calendar="' + wanted + '"]');
    if (link) {
      event.preventDefault();
      link.click();
    }
  });
});
