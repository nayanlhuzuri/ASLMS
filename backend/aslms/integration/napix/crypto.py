"""NAPIX request/response envelope (docs/napix_integration_notes.md §3–§4, verified live).

    plain          = "k1=v1|k2=v2"                        documented order; it is the HMAC input
    key            = trim(auth_key) as UTF-8, cut or zero-padded to exactly 16 bytes; the IV is the same bytes
    request_str    = base64( AES-128-CBC( plain, key, iv=key, PKCS7 ) )     the empty string is encrypted too
    request_token  = hex( HMAC-SHA256( plain, "15081947" ) )                over the plain text
    response_str   decrypts the same way; response_token = HMAC-SHA256 of the decrypted text.

Known answers: HMAC("state_code=27") from the Subscriber Manual and HMAC("") from the live test (notes §3.4)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from aslms.core.errors import NapixInputError

DEFAULT_HASH_KEY = "15081947"
KNOWN_ANSWERS = {
    "state_code=27": "d10f8382c089c134ae7635fea97b2ca81488b25f3db23c9d578146599b7679c7",
    "": "6d1c982a5a21d89d2556c5e5ffb7c9e661a7c549512b1dfd6f055d8d78161fd4",
}


def build_plain(params: Mapping[str, object]) -> str:
    """`k=v|k=v` in insertion order; values verbatim (no encoding inside the plain text). A key or value
    holding `|` or `=` would add or change a pair in the request, so it is refused before anything is sent."""
    for k, v in params.items():
        if any(ch in str(k) or ch in str(v) for ch in "|="):
            raise NapixInputError(f"parameter {k!r} would alter the request: '|' and '=' are not allowed")
    return "|".join(f"{k}={v}" for k, v in params.items())


def key_bytes(auth_key: str) -> bytes:
    """Notes §3.2: trimmed UTF-8 text, cut to 16 bytes or padded with zero bytes to 16."""
    return auth_key.strip().encode("utf-8")[:16].ljust(16, b"\0")


class NapixCrypto:
    def __init__(self, auth_key: str, hash_key: str = DEFAULT_HASH_KEY):
        self._key = key_bytes(auth_key)
        self._hash_key = hash_key.encode("ascii")

    @property
    def fingerprint(self) -> str:
        """First 8 hex chars of sha256(key): safe to log, lets two setups compare keys."""
        return hashlib.sha256(self._key).hexdigest()[:8]

    def encrypt(self, plain: str) -> str:
        padder = padding.PKCS7(128).padder()
        data = padder.update(plain.encode("utf-8")) + padder.finalize()
        enc = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).encryptor()
        return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")

    def decrypt(self, b64: str) -> str:
        """Raw ciphertext only (no OpenSSL `Salted__` handling). Raises ValueError on a wrong key."""
        try:
            raw = base64.b64decode("".join(str(b64).split()), validate=False)
            dec = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).decryptor()
            data = dec.update(raw) + dec.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            return (unpadder.update(data) + unpadder.finalize()).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError) as e:
            raise ValueError(
                f"cannot decrypt NAPIX payload ({type(e).__name__}); check NAPIX_AUTH_KEY"
            ) from e

    def token(self, plain: str) -> str:
        return hmac.new(self._hash_key, plain.encode("utf-8"), hashlib.sha256).hexdigest()

    def self_test(self) -> bool:
        """The hash key is fixed by the spec; the known answers prove the HMAC side is right."""
        return all(self.token(p) == t for p, t in KNOWN_ANSWERS.items())
