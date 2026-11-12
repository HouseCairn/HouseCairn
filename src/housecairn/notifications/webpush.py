"""Web Push on `cryptography` alone: message encryption (RFC 8291) and VAPID (RFC 8292).

docs/adr/0066. No other dependency: `cryptography` is already one (docs/adr/0035) and gives
every primitive needed, P-256 ECDH, HKDF, AES-128-GCM and ECDSA with SHA-256.

- `encrypt` seals a payload for one subscription with the `aes128gcm` content coding of
  RFC 8188, as RFC 8291 prescribes: a key pair of the application server made for that
  message alone, a random salt, one record. The push service carries bytes it cannot read.
- `vapid_header` signs a JWT (ES256) whose audience is the origin of the push service, with
  the key pair of the instance (`models.PushKey`), so that the push service knows which
  server sends and the subscription made with that public key only accepts its messages.
- `post` sends one message through `core.netguard.post`: HTTPS on port 443, every address
  of the name public, no redirect, `SEND_SECONDS` in all.

Nothing here logs an endpoint or a key: an endpoint is a capability (whoever has it can
push to the device, with the key of the instance).
"""

import base64
import json
import os
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from housecairn.core import netguard

RECORD_SIZE = 4096
# What a push service must accept (RFC 8030, 7.2): 4096 octets of encrypted payload. The
# header (86) and the tag of AES-GCM (16) and the delimiter (1) leave this for the text.
MAX_PAYLOAD = RECORD_SIZE - 86 - 16 - 1
TTL_SECONDS = 24 * 3600
JWT_SECONDS = 12 * 3600
SEND_SECONDS = 8.0


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    clean = "".join(text.split())
    return base64.urlsafe_b64decode(clean + "=" * (-len(clean) % 4))


def _hmac(key: bytes, data: bytes) -> bytes:
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(data)
    return mac.finalize()


def public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    """The uncompressed point, 65 octets: the form Web Push uses for every public key."""
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def load_public(raw: bytes) -> ec.EllipticCurvePublicKey:
    """A P-256 public key in uncompressed form; ValueError otherwise."""
    if len(raw) != 65 or raw[0] != 4:
        raise ValueError("not an uncompressed P-256 point")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


def private_from_bytes(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def private_bytes(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_numbers().private_value.to_bytes(32, "big")


def new_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@dataclass(frozen=True)
class Derived:
    """The values RFC 8291 names, kept for the tests against its Appendix A."""

    ecdh_secret: bytes
    prk_key: bytes
    ikm: bytes
    prk: bytes
    cek: bytes
    nonce: bytes


def derive(
    *,
    ua_public: bytes,
    auth_secret: bytes,
    salt: bytes,
    as_private: ec.EllipticCurvePrivateKey,
) -> Derived:
    """RFC 8291, section 3.4, then RFC 8188, section 2.2."""
    as_public = public_bytes(as_private.public_key())
    ecdh_secret = as_private.exchange(ec.ECDH(), load_public(ua_public))
    prk_key = _hmac(auth_secret, ecdh_secret)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hmac(prk_key, key_info + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    return Derived(ecdh_secret, prk_key, ikm, prk, cek, nonce)


def encrypt(
    plaintext: bytes,
    *,
    ua_public: bytes,
    auth_secret: bytes,
    salt: bytes | None = None,
    as_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """The body of a push message: header (salt, record size, key) then one record.

    `salt` and `as_private` are for the tests only: each message gets new ones.
    """
    if len(plaintext) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    if len(auth_secret) != 16:
        raise ValueError("the authentication secret is 16 octets")
    salt = salt if salt is not None else os.urandom(16)
    as_private = as_private if as_private is not None else new_key()
    keys = derive(ua_public=ua_public, auth_secret=auth_secret, salt=salt, as_private=as_private)
    as_public = public_bytes(as_private.public_key())
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    record = AESGCM(keys.cek).encrypt(keys.nonce, plaintext + b"\x02", None)
    return header + record


def decrypt(body: bytes, *, ua_private: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    """What a browser does with `encrypt`'s output; for the tests and the fake push service."""
    salt, idlen = body[:16], body[20]
    as_public = body[21 : 21 + idlen]
    ua_public = public_bytes(ua_private.public_key())
    ecdh_secret = ua_private.exchange(ec.ECDH(), load_public(as_public))
    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
    return plain.rstrip(b"\x00")[:-1]


def origin(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def vapid_header(
    endpoint: str, key: ec.EllipticCurvePrivateKey, subject: str, now: float | None = None
) -> str:
    """`Authorization: vapid t=<JWT>, k=<public key>` (RFC 8292, section 3)."""
    issued = int(now if now is not None else time.time())
    head = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = {"aud": origin(endpoint), "exp": issued + JWT_SECONDS, "sub": subject}
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{head}.{body}".encode("ascii")
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = f"{head}.{body}.{b64url(signature)}"
    return f"vapid t={token}, k={b64url(public_bytes(key.public_key()))}"


def post(endpoint: str, *, body: bytes, authorization: str, urgency: str = "normal") -> int:
    """Send one encrypted message; the HTTP status, or `netguard.RefusedError`."""
    return netguard.post(
        endpoint,
        body=body,
        headers={
            "Authorization": authorization,
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_SECONDS),
            "Urgency": urgency,
        },
        seconds=SEND_SECONDS,
    )
