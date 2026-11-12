/* "Receive on this device" (docs/adr/0066). The permission is asked on the click only;
   the subscription of the browser goes to the API with the session and its form token,
   then the page reloads with the device in the list. Nothing else is sent. */
"use strict";

(function () {
  function token() {
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")["X-CSRFToken"] || "";
    } catch (error) {
      return "";
    }
  }

  function key(text) {
    const padded = (text + "===".slice((text.length + 3) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  }

  function show(form, name) {
    form.querySelectorAll("[data-webpush-unsupported], [data-webpush-denied], [data-webpush-failed]").forEach((node) => {
      node.hidden = !node.hasAttribute(name);
    });
  }

  async function subscribe(form) {
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      show(form, "data-webpush-unsupported");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      show(form, "data-webpush-denied");
      return;
    }
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: key(form.dataset.key),
    });
    const data = subscription.toJSON();
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
      body: JSON.stringify({
        name: form.elements.name.value,
        endpoint: data.endpoint,
        p256dh: data.keys.p256dh,
        auth: data.keys.auth,
      }),
    });
    if (!response.ok) {
      show(form, "data-webpush-failed");
      return;
    }
    window.location.reload();
  }

  document.querySelectorAll("form[data-webpush]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) {
        return;
      }
      subscribe(form).catch(() => show(form, "data-webpush-failed"));
    });
  });
})();
