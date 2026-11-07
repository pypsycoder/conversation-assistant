"""Download the public CA linked by official GigaChat docs; no system changes."""
import hashlib
import json
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
directory = ROOT / "data/benchmarks/config"
directory.mkdir(parents=True, exist_ok=True)
with urllib.request.urlopen(URL, timeout=45) as response:
    pem = response.read().decode("ascii")
der = ssl.PEM_cert_to_DER_cert(pem)
context = ssl.create_default_context()
context.load_verify_locations(cadata=pem)
destination = directory / "russian_trusted_root_ca.pem"
destination.write_text(pem, encoding="ascii")
details = ssl._ssl._test_decode_cert(str(destination))
metadata = {"source": URL, "source_tls_verified": True, "sha256_der": hashlib.sha256(der).hexdigest(),
            "subject": details["subject"], "issuer": details["issuer"], "not_after": details["notAfter"],
            "scope": "Only explicitly loaded into this project's GigaChat HTTPS client; not installed in OS"}
(directory / "gigachat-ca-provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(metadata, ensure_ascii=False, indent=2))
