/* Installs the service worker and shows the offline state (docs/adr/0065).

   Loaded by every page (templates/shell/pwa_head.html), which gives the address of the
   worker, its scope, and whether someone is signed in:

   - signed out, the service worker drops every page it kept;
   - a page served from the cache (the service worker marks it), or a page whose
     connection drops, shows the banner "Offline: data from <date>" and turns off every
     button that writes. Nothing is queued: back online, the buttons of a live page come
     back; a kept page stays read-only until the next page is opened. */
(function () {
  "use strict";

  var script = document.currentScript;
  var WRITES =
    'form[method="post"] button, form[method="post"] input[type="submit"], ' +
    "[hx-post], [hx-put], [hx-patch], [hx-delete]";

  if (script && "serviceWorker" in navigator && window.isSecureContext) {
    var worker = navigator.serviceWorker;
    worker.register(script.dataset.worker, { scope: script.dataset.scope }).catch(function () {
      // No service worker (private window, storage refused): the application still works.
    });
    if (script.dataset.signedIn !== "true") {
      worker.ready.then(function (registration) {
        if (registration.active) {
          registration.active.postMessage({ type: "purge" });
        }
      });
    }
  }

  var banner = document.getElementById("offline-banner");
  if (!banner) {
    return;
  }
  var fromCache = banner.getAttribute("data-served") === "cache";
  var offline = false;

  function turnWrites(off) {
    document.querySelectorAll(WRITES).forEach(function (element) {
      if (off && !element.disabled) {
        element.disabled = true;
        element.setAttribute("data-offline-off", "");
        var described = element.getAttribute("aria-describedby");
        element.setAttribute("aria-describedby", described ? described + " offline-banner" : "offline-banner");
      } else if (!off && element.hasAttribute("data-offline-off")) {
        element.disabled = false;
        element.removeAttribute("data-offline-off");
        var rest = (element.getAttribute("aria-describedby") || "")
          .split(" ")
          .filter(function (id) { return id && id !== "offline-banner"; });
        if (rest.length) {
          element.setAttribute("aria-describedby", rest.join(" "));
        } else {
          element.removeAttribute("aria-describedby");
        }
      }
    });
  }

  function show(off) {
    offline = off;
    banner.hidden = !off;
    document.documentElement.classList.toggle("is-offline", off);
    turnWrites(off);
  }

  show(fromCache || !navigator.onLine);
  window.addEventListener("offline", function () {
    show(true);
  });
  // A kept page stays as it is, banner included, until the person opens a page again: a
  // reload of its own could replace the navigation the person just started.
  window.addEventListener("online", function () {
    if (!fromCache) {
      show(false);
    }
  });
  // What HTMX brings in while offline is turned off too.
  document.addEventListener("htmx:afterSettle", function () {
    if (offline) {
      turnWrites(true);
    }
  });
})();
