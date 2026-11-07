/* HouseCairn documentation site (docs/adr/0016, "Design"). A code block or a
   table wider than the page scrolls sideways: it is made reachable with the
   Tab key so that it can be scrolled without a mouse (WCAG 2.1.1). */
"use strict";

function makeScrollableRegionsFocusable() {
  document.querySelectorAll("article pre, article .table-wrapper").forEach((element) => {
    const scrolls = element.scrollWidth > element.clientWidth;
    if (scrolls && !element.hasAttribute("tabindex")) {
      element.setAttribute("tabindex", "0");
    } else if (!scrolls && element.getAttribute("tabindex") === "0") {
      element.removeAttribute("tabindex");
    }
  });
}

document.addEventListener("DOMContentLoaded", makeScrollableRegionsFocusable);
window.addEventListener("resize", makeScrollableRegionsFocusable);
