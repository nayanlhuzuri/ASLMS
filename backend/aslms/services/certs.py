"""An internal certificate authority for a closed network (design deployment-checklist, decision 7):
`aslms ops make-cert --host <name> [--ip <address>] --out infra/proxy/certs` writes a CA certificate and key and a
server certificate (host name and address as SANs, valid 825 days) signed by it, as `fullchain.pem` and
`privkey.pem` for the proxy. The CA certificate is installed once on each pilot PC; `ca.key` is moved off the host."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SERVER_DAYS = 825
CA_DAYS = 3650


@dataclass(frozen=True)
class CertFiles:
    ca_cert: Path
    ca_key: Path
    fullchain: Path
    privkey: Path


def _write(path: Path, data: bytes, private: bool) -> None:
    path.write_bytes(data)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass


def _key_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def make_cert(
    host: str, out: str | Path, ips: list[str] | None = None, now: datetime | None = None
) -> CertFiles:
    if not host or any(c.isspace() for c in host):
        raise ValueError("--host must be a host name without spaces")
    addresses = [ipaddress.ip_address(a) for a in (ips or [])]
    now = now or datetime.now(UTC)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ASLMS pilot"),
            x509.NameAttribute(NameOID.COMMON_NAME, "ASLMS internal CA"),
        ]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = [x509.DNSName(host)]
    sans += [x509.IPAddress(a) for a in addresses]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    files = CertFiles(
        out_dir / "ca.crt", out_dir / "ca.key", out_dir / "fullchain.pem", out_dir / "privkey.pem"
    )
    _write(files.ca_cert, ca_cert.public_bytes(serialization.Encoding.PEM), False)
    _write(files.ca_key, _key_pem(ca_key), True)
    _write(
        files.fullchain,
        cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM),
        False,
    )
    _write(files.privkey, _key_pem(key), True)
    return files
