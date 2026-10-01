"""Create a short-lived test certificate inside an isolated Docker volume (no ACME)."""
import datetime
import ipaddress
import os
from pathlib import Path
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

challenge = Path("/var/www/certbot/.well-known/acme-challenge/probe")
challenge.parent.mkdir(parents=True, exist_ok=True)
challenge.write_text("challenge-value")
if len(sys.argv) > 1 and sys.argv[1] == "challenge":
    sys.exit(0)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.example.test")])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(subject).issuer_name(subject).public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(minutes=1))
    .not_valid_after(now + datetime.timedelta(days=2))
    .add_extension(x509.SubjectAlternativeName([
        x509.DNSName("api.example.test"), x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]), critical=False)
    .sign(key, hashes.SHA256())
)
directory = Path("/etc/letsencrypt/live/doctrace")
directory.mkdir(parents=True, exist_ok=True)
directory.joinpath("privkey.pem").write_bytes(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
))
os.chmod(directory / "privkey.pem", 0o600)
pem = cert.public_bytes(serialization.Encoding.PEM)
directory.joinpath("fullchain.pem").write_bytes(pem)
print(pem.decode(), end="")  # Only the public certificate, used as the test client's CA.
