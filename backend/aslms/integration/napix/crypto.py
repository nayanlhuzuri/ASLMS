"""NAPIX request/response envelope (HC Open API v1.0, Annexure A; Subscriber Manual Annexure B).

    plain          = "k1=v1|k2=v2"                       (documented parameter order; it matters for the HMAC)
    request_str    = base64( AES-128-CBC( plain, key = auth_key, iv = auth_key, PKCS7 ) )
    request_token  = hex( HMAC-SHA256( plain, key = hash_key ) )     hash_key is the fixed "15081947"
    response_str   decrypts the same way; response_token = HMAC-SHA256 of the decrypted text.

The authentication key is 16 characters. NAPIX's reference implementation (PHP openssl) pads a shorter key
with NUL bytes and truncates a longer one, and uses the same bytes as the IV; `key_mode` says whether the key
you were given is plain text, hex or base64. Known answer from the Subscriber Manual:
HMAC("state_code=27") = d10f8382c089c134ae7635fea97b2ca81488b25f3db23c9d578146599b7679c7.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_HASH_KEY = "15081947"
KNOWN_ANSWER_PLAIN = "state_code=27"
KNOWN_ANSWER_TOKEN = "d10f8382c089c134ae7635fea97b2ca81488b25f3db23c9d578146599b7679c7"


def build_plain(params: Mapping[str, object]) -> str:
    """`k=v|k=v` in insertion order. Values are used verbatim (no URL encoding inside the plain text)."""
    return "|".join(f"{k}={v}" for k, v in params.items())


def key_bytes(auth_key: str, key_mode: str = "text") -> bytes:
    raw = auth_key.strip()
    mode = (key_mode or "text").lower()
    if mode == "hex":
        kb = bytes.fromhex(raw)
    elif mode == "base64":
        kb = base64.b64decode(raw)
    elif mode == "text":
        kb = raw.encode("utf-8")
    else:
        raise ValueError(f"unknown key_mode {key_mode!r}; expected text, hex or base64")
    return kb.ljust(16, b"\0")[:16]


class NapixCrypto:
    def __init__(self, auth_key: str, hash_key: str = DEFAULT_HASH_KEY, key_mode: str = "text"):
        self._key = key_bytes(auth_key, key_mode)
        self._hash_key = hash_key.encode("ascii")

    @property
    def fingerprint(self) -> str:
        """First 8 hex chars of sha256(key): safe to log, reveals nothing, lets two setups compare keys."""
        return hashlib.sha256(self._key).hexdigest()[:8]

    def encrypt(self, plain: str) -> str:
        padder = padding.PKCS7(128).padder()
        data = padder.update(plain.encode("utf-8")) + padder.finalize()
        enc = Cipher(algorithms.AES(self._key), modes.CBC(self._key)).encryptor()
        return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")

    def decrypt(self, b64: str) -> str:
        """Raises ValueError when the key is wrong or the payload is not what NAPIX produces."""
        try:
            raw = base64.b64decode(b64.replace("\\/", "/").strip(), validate=False)
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
        """The hash key is fixed by the spec; this proves it is set correctly."""
        return self.token(KNOWN_ANSWER_PLAIN) == KNOWN_ANSWER_TOKEN
