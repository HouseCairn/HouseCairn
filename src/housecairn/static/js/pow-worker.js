/* Worker of the proof of work of open sign-up (docs/adr/0024).
 *
 * Looks for n such that SHA-256 of "<challenge>:<n>" starts with `bits` zero bits,
 * away from the page, which stays responsive while it works.
 */
'use strict'

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

// Bounds of the difficulty: the same as HOUSECAIRN_SIGNUP_POW_BITS (settings.py).
const MIN_BITS = 8
const MAX_BITS = 24
const CHALLENGE = /^[A-Za-z0-9_-]{8,128}$/

// A dedicated worker is created by pow.js and only that page can post to it, so the
// origin of a message is the empty string. Anything else is refused explicitly (a
// message from another origin must never start the search), and so is any message
// that is not exactly { challenge: string, bits: integer within bounds }.
function wellFormed (data) {
  return (
    data !== null &&
    typeof data === 'object' &&
    typeof data.challenge === 'string' &&
    CHALLENGE.test(data.challenge) &&
    Number.isInteger(data.bits) &&
    data.bits >= MIN_BITS &&
    data.bits <= MAX_BITS
  )
}

self.onmessage = async (event) => {
  if (event.origin !== '' && event.origin !== self.location.origin) {
    return
  }
  if (!wellFormed(event.data)) {
    return
  }
  const { challenge, bits } = event.data
  const encoder = new TextEncoder()
  for (let n = 0; ; n++) {
    const digest = await self.crypto.subtle.digest('SHA-256', encoder.encode(challenge + ':' + n))
    if (zeroBits(new Uint8Array(digest)) >= bits) {
      self.postMessage(String(n))
      return
    }
  }
}
