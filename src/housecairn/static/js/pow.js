/* Proof of work of open sign-up (docs/adr/0024).
 *
 * The form carries a challenge and a number of zero bits in the data attributes
 * of its hidden `pow_solution` field. While the person fills the form in, this
 * script looks for a number n such that SHA-256 of "<challenge>:<n>" starts with
 * that many zero bits, then puts n in the field. The server checks it with one
 * hash. The submit button waits for it. No inline script, no third-party code;
 * SubtleCrypto needs a secure context (HTTPS, or localhost).
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

  if (!window.crypto || !window.crypto.subtle) {
    say('unavailable')
    return
  }
  hold(true)
  say('working')

  function zeroBits (bytes) {
    let bits = 0
    for (const byte of bytes) {
      if (byte === 0) {
        bits += 8
        continue
      }
      return bits + Math.clz32(byte) - 24
    }
    return bits
  }

  async function solve (challenge, wanted) {
    const encoder = new TextEncoder()
    for (let n = 0; ; n++) {
      const digest = await window.crypto.subtle.digest('SHA-256', encoder.encode(challenge + ':' + n))
      if (zeroBits(new Uint8Array(digest)) >= wanted) {
        return String(n)
      }
    }
  }

  solve(field.dataset.challenge, parseInt(field.dataset.bits, 10)).then((n) => {
    field.value = n
    hold(false)
    say('done')
  })
})()
