/* Passkey sign-in without a button (docs/adr/0018).
 *
 * 1. Where the browser supports conditional mediation, the passkeys saved for
 *    this site appear in the autofill list of the address field
 *    (autocomplete="username webauthn"); picking one signs the person in.
 * 2. Elsewhere, an offer to use a passkey appears under the field as soon as
 *    something is typed in it. It is shown whatever the address: asking the
 *    server whether an account has a passkey would reveal which addresses are
 *    registered.
 *
 * allauth gives the endpoint that hands out the challenge (a GET asking for JSON
 * on the passkey login URL) and the one that checks the signed answer (a POST of
 * the form). webauthn-json.js, also from allauth, converts between the browser
 * API and JSON. No inline script, no third-party code.
 */
(function () {
  'use strict'

  const form = document.getElementById('mfa_login')
  const field = document.querySelector('input[autocomplete~="webauthn"]')
  const webauthnJSON = window.webauthnJSON
  if (!form || !field || !webauthnJSON || !window.PublicKeyCredential) {
    return
  }
  const credentialInput = document.getElementById('mfa_credential')
  const signInForm = field.form
  let pending = null

  async function fetchOptions () {
    const response = await fetch(form.dataset.optionsUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin'
    })
    if (!response.ok) {
      throw new Error('Unable to fetch the passkey challenge.')
    }
    return (await response.json()).request_options
  }

  async function signIn (conditional) {
    const options = await fetchOptions()
    const request = Object.assign({}, options)
    if (conditional) {
      pending = new AbortController()
      request.mediation = 'conditional'
      request.signal = pending.signal
    }
    const credential = await webauthnJSON.get(request)
    credentialInput.value = JSON.stringify(credential)
    form.submit()
  }

  function say (message) {
    let status = document.getElementById('passkey-status')
    if (!status) {
      status = document.createElement('p')
      status.id = 'passkey-status'
      status.className = 'small'
      status.setAttribute('role', 'status')
      field.parentNode.after(status)
    }
    status.textContent = message
  }

  function offer () {
    const holder = document.createElement('p')
    holder.className = 'passkey-offer'
    holder.hidden = true
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'button-secondary button-block'
    button.textContent = form.dataset.offerLabel
    button.title = form.dataset.offerHint
    button.addEventListener('click', async function () {
      try {
        await signIn(false)
      } catch (error) {
        if (error && error.name !== 'NotAllowedError' && error.name !== 'AbortError') {
          say(form.dataset.error)
        }
      }
    })
    holder.appendChild(button)
    field.parentNode.after(holder)
    field.addEventListener('input', function () {
      holder.hidden = field.value.trim() === ''
    })
  }

  async function start () {
    let conditional = false
    if (typeof PublicKeyCredential.isConditionalMediationAvailable === 'function') {
      try {
        conditional = await PublicKeyCredential.isConditionalMediationAvailable()
      } catch (error) {
        conditional = false
      }
    }
    if (!conditional) {
      offer()
      return
    }
    // Typing a password instead cancels the pending passkey request.
    signInForm.addEventListener('submit', function () {
      if (pending) {
        pending.abort()
      }
    })
    try {
      await signIn(true)
    } catch (error) {
      // Nobody asked for this request: failing quietly leaves the password form as is.
    }
  }

  start()
})()
