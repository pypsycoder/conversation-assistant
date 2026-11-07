"""Explicit cloud experiment: GigaChat OAuth, verified TLS, no credential logging."""
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from .extraction import SCHEMA, SYSTEM, SYSTEM_V2, evidence_errors
from .validation import loads

ROOT = Path(__file__).resolve().parents[1]
AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_BASES = {"https://api.giga.chat/v1", "https://gigachat.devices.sberbank.ru/api/v1"}
CREDENTIAL_NAMES = ("GIGACHAT_CREDENTIALS", "GIGACHAT_AUTH_KEY", "GIGACHAT_AUTHORIZATION_KEY", "GIGACHAT_API_KEY", "GIGACHAT_KEY_L1", "GIGACHAT_KEY")


def read_dotenv(path):
    """Small literal key=value reader. Never executes or expands file contents."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            raise ValueError("Unsupported .env line; expected literal KEY=value")
        key, value = match.groups()
        if key in values:
            raise ValueError("Duplicate variable name in .env")
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("Unclosed quote in .env")
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


class SafeAPIError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeAPIError("Unexpected HTTP redirect; credentials were not forwarded")


class GigaChatClient:
    def __init__(self, env_path=ROOT / ".env", use_system_proxy=True):
        values = read_dotenv(env_path)
        credential = next((values[key] for key in CREDENTIAL_NAMES if values.get(key)), None)
        if not credential:
            raise ValueError("GigaChat authorization key missing in .env")
        if credential.startswith("Basic "):
            credential = credential[6:].strip()
        if not credential or any(c.isspace() for c in credential):
            raise ValueError("Invalid GigaChat authorization key format")
        self._credential = credential
        self._token = None
        self._expires_at = 0
        self.scope = values.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        if self.scope not in {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}:
            raise ValueError("Unsupported GigaChat scope")
        self.base_url = values.get("GIGACHAT_BASE_URL", "https://api.giga.chat/v1").rstrip("/")
        if self.base_url not in API_BASES:
            raise ValueError("GigaChat base URL must be an official HTTPS endpoint")
        self.configured_model = values.get("GIGACHAT_MODEL")
        self.model = self.configured_model
        context = ssl.create_default_context()
        default_ca = ROOT / "data/benchmarks/config/russian_trusted_root_ca.pem"
        ca_file = values.get("GIGACHAT_CA_BUNDLE") or (str(default_ca) if default_ca.exists() else None)
        if ca_file:
            context.load_verify_locations(cafile=ca_file)
        handlers = [NoRedirect(), urllib.request.HTTPSHandler(context=context)]
        if not use_system_proxy:
            handlers.insert(0, urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    def redact(self, text):
        text = str(text)
        for secret in [self._credential, self._token]:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def _request(self, url, payload=None, oauth=False):
        # URL allowlist is checked independently of .env so auth cannot be redirected.
        if url != AUTH_URL and not any(url.startswith(base + "/") for base in API_BASES):
            raise SafeAPIError("Destination is outside official GigaChat endpoints")
        headers = {"Accept": "application/json"}
        if oauth:
            headers.update({"Authorization": "Basic " + self._credential, "RqUID": str(uuid.uuid4()),
                            "Content-Type": "application/x-www-form-urlencoded"})
            data = urllib.parse.urlencode({"scope": self.scope}).encode("ascii")
        else:
            if not self._token or time.time() >= self._expires_at - 60:
                self.authenticate()
            headers["Authorization"] = "Bearer " + self._token
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
            if data is not None:
                headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=120) as response:
                return loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if oauth:
                raise SafeAPIError(f"OAuth HTTP {error.code}; authorization response body not logged") from None
            detail = self.redact(error.read(12000).decode("utf-8", errors="replace"))
            raise SafeAPIError(f"GigaChat HTTP {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            raise SafeAPIError("GigaChat connection failed: " + self.redact(error.reason)) from None

    def authenticate(self):
        response = self._request(AUTH_URL, oauth=True)
        if not isinstance(response.get("access_token"), str) or not response["access_token"]:
            raise SafeAPIError("OAuth response has no access token")
        self._token = response["access_token"]
        self._expires_at = float(response["expires_at"]) / 1000

    def models(self):
        response = self._request(self.base_url + "/models")
        self.available_models = [entry["id"] for entry in response.get("data", []) if "id" in entry]
        if self.configured_model:
            if self.configured_model not in self.available_models:
                raise SafeAPIError("Configured GigaChat model is not listed by API")
        else:
            preference = ["GigaChat-3-Ultra", "GigaChat-2-Max", "GigaChat-2-Pro", "GigaChat-2", "GigaChat-Max", "GigaChat-Pro", "GigaChat"]
            self.model = next((name for name in preference if name in self.available_models), None)
            if not self.model:
                raise SafeAPIError("No supported chat model listed by API")
        return {"base_url": self.base_url, "scope": self.scope, "available_models": self.available_models,
                "selected_model": self.model, "tls_verification": True, "credentials_logged": False}

    def extract(self, segments, prompt_version="v1", temperature=0.001):
        if not self.model:
            self.models()
        system = {"v1": SYSTEM, "v2": SYSTEM_V2}[prompt_version]
        # GigaChat requires temperature >0 and has no compatible seed/reasoning_effort parameter.
        payload = {"model": self.model, "temperature": temperature, "max_tokens": 1400, "stream": False,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps({"segments": segments}, ensure_ascii=False)}],
                   "response_format": {"type": "json_schema", "schema": SCHEMA, "strict": True}}
        began = time.perf_counter()
        raw = self._request(self.base_url + "/chat/completions", payload)
        seconds = time.perf_counter() - began
        parsed = None
        errors = []
        try:
            choice = raw["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("completion did not finish normally: " + choice["finish_reason"])
            parsed = loads(choice["message"]["content"])
            errors = evidence_errors(parsed, segments)
        except (ValueError, TypeError, KeyError, IndexError) as error:
            errors = [{"message": self.redact(error)}]
        # Authorization headers and OAuth responses never enter this artifact.
        return {"seconds": seconds, "request": payload, "response": raw, "parsed": parsed, "validation_errors": errors}

    def generate_structured(self, system, data, schema, max_tokens=10000, temperature=0.001):
        """Explicit experimental schema; caller performs domain/provenance checks."""
        Draft202012Validator.check_schema(schema)
        if not self.model:
            self.models()
        # Finish authentication outside the measured completion request.
        if not self._token or time.time() >= self._expires_at - 60:
            self.authenticate()
        payload = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens, "stream": False,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
                   "response_format": {"type": "json_schema", "schema": schema, "strict": True}}
        began = time.perf_counter()
        raw = self._request(self.base_url + "/chat/completions", payload)
        seconds = time.perf_counter() - began
        parsed, errors = None, []
        try:
            choice = raw["choices"][0]
            if choice["finish_reason"] != "stop":
                raise ValueError("completion did not finish normally: " + choice["finish_reason"])
            parsed = loads(choice["message"]["content"])
            errors = [{"path": list(e.absolute_path), "message": e.message}
                      for e in Draft202012Validator(schema).iter_errors(parsed)]
        except (ValueError, TypeError, KeyError, IndexError) as error:
            errors = [{"message": self.redact(error)}]
        return {"seconds": seconds, "request": payload, "response": raw, "parsed": parsed, "validation_errors": errors}
