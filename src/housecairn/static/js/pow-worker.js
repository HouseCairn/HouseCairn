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

self.onmessage = async (event) => {
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
