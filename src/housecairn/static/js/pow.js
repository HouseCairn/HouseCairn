/* Proof of work of open sign-up (docs/adr/0024).
 *
 * The form carries a challenge and a number of zero bits in the data attributes
 * of its hidden `pow_solution` field. While the person fills the form in, this
 * script looks for a number n such that SHA-256 of "<challenge>:<n>" starts with
 * that many zero bits, then puts n in the field. The server checks it with one
 * hash. The submit button waits for it. No inline script, no third-party code;
 * SubtleCrypto needs a secure context (HTTPS, or localhost).
 * The search itself is in pow-worker.js.
 */
(function () {
  'use strict'

  const field = document.querySelector('input[data-challenge][data-bits]')
  if (!field) {
    return
  }
  const form = field.form
  const status = form.querySelector('[data-pow-status]')
  const buttons = Array.from(form.querySelectorAll('button[type="submit"]'))
  const say = (key) => {
    if (status) {
      status.textContent = status.dataset[key] || ''
      status.hidden = false
    }
  }
  const hold = (held) => buttons.forEach((b) => { b.disabled = held })

  const workerUrl = document.currentScript && document.currentScript.dataset.worker
  if (!window.Worker || !window.crypto || !window.crypto.subtle || !workerUrl) {
    say('unavailable')
    return
  }
  hold(true)
  say('working')

  // The search runs in a worker, away from the page (static/js/pow-worker.js).
  const worker = new Worker(workerUrl)
  worker.onmessage = (event) => {
    field.value = event.data
    worker.terminate()
    hold(false)
    say('done')
  }
  worker.onerror = () => say('unavailable')
  worker.postMessage({ challenge: field.dataset.challenge, bits: parseInt(field.dataset.bits, 10) })
})()
