// The room the page keeps for the undo banner follows the banner's real height
// (docs/developer/design-guide.md, "Actions in place"). A long message wraps on several
// lines on a narrow screen, so no constant fits. First-party, no library. Without script
// the stylesheet keeps 5rem, the height of one line.
(function () {
  "use strict";
  var region = document.getElementById("undo-region");
  if (!region || !window.ResizeObserver) {
    return;
  }
  var root = document.documentElement;

  function measure() {
    var banner = region.querySelector(".undo-banner");
    root.style.setProperty("--hc-undo-height", (banner ? banner.offsetHeight : 0) + "px");
  }

  // The region changes size when its content is swapped and when the screen is resized.
  new ResizeObserver(measure).observe(region);
  measure();
})();
