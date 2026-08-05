#!/usr/bin/env python3

import argparse
import getpass
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


CONFIG_FILE_NAME = ".summation-config"
DEVICE_LOGIN_STATE_FILE_NAME = ".device-login-state.json"
ACTIVE_PROFILE_KEY = "SUM_API_ACTIVE_PROFILE"
PROFILE_ENV_KEYS = ("SUM_API_PROFILE", "SUMMATION_PROFILE")
CONFIG_PATH_ENV_KEYS = ("SUM_API_CONFIG_FILE", "SUMMATION_CONFIG")
PROFILE_SECTION_PREFIX = "profile."
DEVICE_LOGIN_CREDENTIAL_KEY = "SUM_API_DEVICE_LOGIN_CREDENTIAL"
DEVICE_LOGIN_ALLOWED_SURFACES = (
    "claude-code",
    "claude-desktop",
    "codex",
    "summation-skill",
)
DEVICE_LOGIN_SURFACE_ALIASES = {
    # Auth-service does not allowlist "codex" yet: send the accepted backend label
    # while keeping a friendly client surface in the Codex plugin's instructions.
    "codex": "summation-skill",
}
PROFILE_OVERRIDE: str | None = None
BASE_URL_OVERRIDE: str | None = None
ENV_OVERRIDE: str | None = None

MCP_SERVER_NAME = "summation"

# One artifact for everyone. Internal features (environment selection, M2M, profiles) unlock at
# runtime via the ADDISON_PLUGIN_INTERNAL shell env var — NOT a build flag. This is only safe
# because the environment allowlist below is enforced unconditionally in resolve_request_url():
# the flag can widen what UX is offered, never the set of hosts the bearer credential can reach.
ADDISON_INTERNAL_ENV = "ADDISON_PLUGIN_INTERNAL"

# Every Summation environment the credential may reach. There is no free-form host anywhere.
ALLOWED_ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prod":    {"api": "https://api.summation.com",         "mcp": "https://mcp.summation.com/mcp"},
    "staging": {"api": "https://staging-api.summation.com", "mcp": "https://staging-mcp.summation.com/mcp"},
    "sandbox": {"api": "https://sandbox-api.summation.com", "mcp": "https://sandbox-mcp.summation.com/mcp"},
}
PRODUCTION_BASE_URL = ALLOWED_ENVIRONMENTS["prod"]["api"]
PRODUCTION_MCP_URL = ALLOWED_ENVIRONMENTS["prod"]["mcp"]
ALLOWED_BASE_URLS = {env["api"] for env in ALLOWED_ENVIRONMENTS.values()}


def is_internal() -> bool:
    """Internal edition, unlocked by the ADDISON_PLUGIN_INTERNAL shell env var (1/true/yes/on)."""
    return os.environ.get(ADDISON_INTERNAL_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def skill_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def home_config_path() -> pathlib.Path:
    # Internal (multi-env, M2M, profiles) and external (prod-pinned, device-login-only) keep
    # separate files so a sandbox/staging credential never lands where the prod-only path reads
    # it — and neither collides with the generic ~/.summation/config used by sumcli.
    name = "summation-config-internal" if is_internal() else "summation-config"
    return pathlib.Path.home() / ".summation" / name


def device_login_state_path() -> pathlib.Path:
    return pathlib.Path.home() / ".summation" / DEVICE_LOGIN_STATE_FILE_NAME


def legacy_config_paths() -> list[pathlib.Path]:
    paths = [skill_root() / CONFIG_FILE_NAME, pathlib.Path.home() / CONFIG_FILE_NAME]
    if is_internal():
        # Pre-edition installs stored config here; only internal inherits it (it may hold
        # sandbox base URLs / M2M values the external path must not pick up).
        paths.insert(0, pathlib.Path.home() / ".summation" / "skill-config")
    return paths


def migrate_legacy_config(found: pathlib.Path) -> pathlib.Path:
    canonical = home_config_path()
    if canonical.exists():
        return found
    if found.resolve() not in {path.resolve() for path in legacy_config_paths()}:
        return found
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(found.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(canonical, 0o600)
    print(
        f"Migrated config from {found} to {canonical}; legacy file left in place.",
        file=sys.stderr,
    )
    return canonical


def candidate_config_paths() -> list[pathlib.Path]:
    paths: list[pathlib.Path] = []
    for env_key in CONFIG_PATH_ENV_KEYS:
        explicit = os.getenv(env_key)
        if explicit:
            paths.append(pathlib.Path(explicit).expanduser())
    paths.append(pathlib.Path.cwd() / CONFIG_FILE_NAME)
    paths.append(home_config_path())
    paths.extend(legacy_config_paths())
    seen = set()
    unique_paths = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_paths.append(path)
    return unique_paths


def active_config_path() -> pathlib.Path | None:
    for path in candidate_config_paths():
        if path.exists():
            return migrate_legacy_config(path)
    return None


def parse_config_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].strip()
    if "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def parse_config_section(line: str) -> str | None:
    stripped = line.strip()
    if len(stripped) < 3 or not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    name = stripped[1:-1].strip()
    if name.startswith(PROFILE_SECTION_PREFIX):
        name = name[len(PROFILE_SECTION_PREFIX):]
    return name or None


def empty_config() -> dict[str, Any]:
    return {"values": {}, "profiles": {}}


def read_config_from_path(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return empty_config()
    values: dict[str, str] = {}
    profiles: dict[str, dict[str, str]] = {}
    current_profile: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        section = parse_config_section(line)
        if section:
            current_profile = section
            profiles.setdefault(current_profile, {})
            continue
        parsed = parse_config_line(line)
        if parsed:
            key, value = parsed
            if current_profile:
                profiles.setdefault(current_profile, {})[key] = value
            else:
                values[key] = value
    return {"values": values, "profiles": profiles}


def read_config() -> dict[str, Any]:
    path = active_config_path()
    if not path:
        return empty_config()
    return read_config_from_path(path)


CONFIG = read_config()


def config_values() -> dict[str, str]:
    values = CONFIG.get("values", {})
    return values if isinstance(values, dict) else {}


def config_profiles() -> dict[str, dict[str, str]]:
    profiles = CONFIG.get("profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def profile_name_from(values: dict[str, str], profiles: dict[str, dict[str, str]]) -> str | None:
    if PROFILE_OVERRIDE:
        return PROFILE_OVERRIDE
    for key in PROFILE_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return value
    configured = values.get(ACTIVE_PROFILE_KEY)
    if configured:
        return configured
    if "default" in profiles:
        return "default"
    if len(profiles) == 1:
        return next(iter(profiles))
    return None


def selected_profile_name() -> str | None:
    return profile_name_from(config_values(), config_profiles())


def selected_profile_values() -> dict[str, str]:
    profile = selected_profile_name()
    if not profile:
        return {}
    return config_profiles().get(profile, {})


def setting(name: str, default: str | None = None) -> str | None:
    value = selected_profile_values().get(name)
    if value is not None and value != "":
        return value
    value = config_values().get(name)
    if value is not None and value != "":
        return value
    value = os.getenv(name)
    if value is not None and value != "":
        return value
    return default


def _env_for_url(url: str) -> str:
    """Map an allowlisted api URL back to its environment name; reject anything else."""
    normalized = url.rstrip("/")
    for name, urls in ALLOWED_ENVIRONMENTS.items():
        if urls["api"] == normalized:
            return name
    raise SystemExit(
        f"{url} is not an allowed Summation environment "
        f"(choose from {', '.join(sorted(ALLOWED_ENVIRONMENTS))})"
    )


def selected_env() -> str:
    """The pinned environment name. External is always prod; internal resolves the selection:
    --env, then the host the current device-login is polling, then stored config, then prod."""
    if not is_internal():
        return "prod"
    if ENV_OVERRIDE:
        return ENV_OVERRIDE
    if BASE_URL_OVERRIDE:
        return _env_for_url(BASE_URL_OVERRIDE)
    stored = setting("SUM_API_BASE_URL")
    if stored:
        return _env_for_url(stored)
    return "prod"


def base_url() -> str:
    if not is_internal() and ENV_OVERRIDE and ENV_OVERRIDE != "prod":
        raise SystemExit(
            f"--env {ENV_OVERRIDE} needs {ADDISON_INTERNAL_ENV}=1 "
            f"(the plugin is production-only unless internal mode is enabled)"
        )
    return ALLOWED_ENVIRONMENTS[selected_env()]["api"]


def normalize_device_login_credential(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.startswith("sm_dls_"):
        raise SystemExit(
            f"{DEVICE_LOGIN_CREDENTIAL_KEY} must start with 'sm_dls_'"
        )
    return normalized


def device_login_credential() -> str | None:
    return normalize_device_login_credential(setting(DEVICE_LOGIN_CREDENTIAL_KEY))


def auth_mode(
    *,
    values: dict[str, str] | None = None,
    selected_values: dict[str, str] | None = None,
) -> str | None:
    if values is None:
        if device_login_credential():
            return "device_login"
        if setting("SUM_API_ACCESS_TOKEN"):
            return "access_token"
        if setting("SUM_API_CLIENT_ID") and setting("SUM_API_CLIENT_SECRET"):
            return "m2m"
        return None

    def value_for(key: str) -> str | None:
        if key in values:
            value = values.get(key)
            return value if value else None
        if selected_values and key in selected_values:
            value = selected_values.get(key)
            return value if value else None
        return None

    if normalize_device_login_credential(value_for(DEVICE_LOGIN_CREDENTIAL_KEY)):
        return "device_login"
    if value_for("SUM_API_ACCESS_TOKEN"):
        return "access_token"
    if value_for("SUM_API_CLIENT_ID") and value_for("SUM_API_CLIENT_SECRET"):
        return "m2m"
    return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _device_login_state_key(profile_name: str | None, base_url_value: str) -> str:
    if profile_name:
        return f"profile:{profile_name}"
    return f"base_url:{base_url_value.rstrip('/')}"


def _read_device_login_states() -> dict[str, dict[str, Any]]:
    path = device_login_state_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Device-login state file is unreadable: {path} ({exc})") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Device-login state file is invalid: {path}")
    states: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            states[key] = value
    return states


def _write_device_login_states(states: dict[str, dict[str, Any]]) -> pathlib.Path:
    path = device_login_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(states, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def store_pending_device_login(
    *,
    profile_name: str | None,
    surface: str,
    device_code: str,
    interval: int,
    expires_in: int,
) -> pathlib.Path:
    now = time.time()
    state = {
        "profile": profile_name,
        "base_url": base_url(),
        "surface": surface,
        "device_code": device_code,
        "interval": interval,
        "expires_in": expires_in,
        "created_at": now,
        "expires_at": now + expires_in,
    }
    states = _read_device_login_states()
    states[_device_login_state_key(profile_name, base_url())] = state
    return _write_device_login_states(states)


def load_pending_device_login(profile_name: str | None) -> tuple[str, dict[str, Any]]:
    states = _read_device_login_states()
    if profile_name:
        key = _device_login_state_key(profile_name, base_url())
        state = states.get(key)
        if state is not None:
            return key, state
        profile_key = f"profile:{profile_name}"
        state = states.get(profile_key)
        if state is not None:
            return profile_key, state
        raise SystemExit(
            f"No pending device login for profile '{profile_name}'. Run the login command again."
        )
    if not states:
        raise SystemExit("No pending device login found. Run the login command again.")
    if len(states) == 1:
        return next(iter(states.items()))
    raise SystemExit(
        "Multiple pending device logins exist. Re-run with --profile to select one."
    )


def clear_pending_device_login(profile_name: str | None, base_url_value: str) -> pathlib.Path | None:
    path = device_login_state_path()
    if not path.exists():
        return None
    states = _read_device_login_states()
    states.pop(_device_login_state_key(profile_name, base_url_value), None)
    if states:
        _write_device_login_states(states)
    else:
        path.unlink()
    return path


def parse_json_arg(raw: str | None, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON argument: {exc}") from exc


def ssl_context() -> ssl.SSLContext | None:
    cert_file = setting("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    if cert_file:
        return ssl.create_default_context(cafile=cert_file)
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def format_url_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        return (
            "Request failed: TLS certificate verification failed. "
            "Set SSL_CERT_FILE to a CA bundle path, or install certifi in this Python environment."
        )
    return f"Request failed: {exc}"


def audit_path() -> pathlib.Path:
    return pathlib.Path.home() / ".summation" / "audit.jsonl"


def _request_id_from(headers: Any, detail: Any) -> str | None:
    if headers is not None:
        for key in ("x-request-id", "request-id", "x-amzn-requestid"):
            value = headers.get(key)
            if value:
                return value
    if isinstance(detail, dict):
        for key in ("request_id", "requestId"):
            value = detail.get(key)
            if value:
                return str(value)
        error = detail.get("error")
        if isinstance(error, dict):
            value = error.get("request_id")
            if value:
                return str(value)
    return None


def _audit(method: str, url: str, started: float, status: int | None, request_id: str | None, error: str | None = None) -> None:
    # Best-effort, never raises, never records bodies, headers, or query strings.
    try:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": method.upper(),
            "path": urllib.parse.urlsplit(url).path,
            "status": status,
            "duration_ms": int((time.time() - started) * 1000),
            "request_id": request_id,
            "profile": selected_profile_name(),
        }
        if error:
            record["error"] = error
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        os.chmod(path, 0o600)
    except Exception:
        pass


def resolve_request_url(path_or_url: str) -> str:
    """Resolve a path (or absolute URL) against base_url(), refusing any other host.

    Every request carries the caller's bearer credential, so the destination is pinned to
    the configured base host — always an allowlisted Summation environment — and must use HTTPS.
    """
    base = urllib.parse.urlsplit(base_url())
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        target = urllib.parse.urlsplit(path_or_url)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
            raise SystemExit(
                f"refusing to call {target.scheme}://{target.netloc}: "
                f"requests are pinned to {base.scheme}://{base.netloc}"
            )
        url = path_or_url
    else:
        path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
        url = f"{base_url()}{path}"
    if base.scheme != "https":
        # base_url() only ever returns an allowlisted https host; this is defense-in-depth.
        raise SystemExit(f"refusing non-HTTPS base URL {base.scheme}://{base.netloc}: credentials require HTTPS")
    return url


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib's default redirect handler re-sends all headers (including Authorization) to
    whatever host a 30x names, with no scheme/host check. Re-pin every redirect target so a
    redirect can never carry the bearer off the configured base host or downgrade to http."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 (urllib API)
        resolve_request_url(newurl)  # raises SystemExit if newurl leaves the pinned origin
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen(req: urllib.request.Request, timeout: int):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_context()),
        _PinnedRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


def request_json(
    method: str,
    path_or_url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    query: dict[str, Any] | None = None,
    form: bool = False,
) -> Any:
    url = resolve_request_url(path_or_url)

    if query:
        clean_query = {
            key: str(value)
            for key, value in query.items()
            if value is not None
        }
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(clean_query)}"

    data = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=request_headers, method=method.upper())
    started = time.time()
    try:
        with _urlopen(req, timeout=60) as response:
            raw = response.read()
            _audit(method, url, started, response.status, _request_id_from(response.headers, None))
            if not raw:
                return None
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type:
                return raw.decode("utf-8", errors="replace")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        _audit(method, url, started, exc.code, _request_id_from(exc.headers, detail), error=str(exc.reason))
        raise SystemExit(json_dumps({
            "error": {
                "status": exc.code,
                "reason": exc.reason,
                "body": detail,
            }
        })) from exc
    except urllib.error.URLError as exc:
        _audit(method, url, started, None, None, error=str(exc.reason))
        raise SystemExit(format_url_error(exc)) from exc


def fetch_openapi() -> dict[str, Any]:
    return request_json("GET", "/openapi.json")


def exchange_m2m_token() -> str:
    client_id = setting("SUM_API_CLIENT_ID")
    client_secret = setting("SUM_API_CLIENT_SECRET")
    scope = setting("SUM_API_M2M_SCOPE")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set SUM_API_ACCESS_TOKEN, or configure SUM_API_CLIENT_ID and SUM_API_CLIENT_SECRET"
        )

    body: dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        body["scope"] = scope

    response = request_json("POST", "/v1/auth/m2m/token", body=body, form=True)
    token = response.get("access_token") if isinstance(response, dict) else None
    if not token:
        raise SystemExit("M2M token response did not include access_token")
    return token


def auth_headers(required: bool = True) -> dict[str, str]:
    token = device_login_credential()
    if not token:
        token = setting("SUM_API_ACCESS_TOKEN")
    if not token and required:
        if not is_internal():
            raise SystemExit("Not signed in to Summation. Run $addison-signin to connect.")
        token = exchange_m2m_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def resolve_refs(node: Any, spec: dict[str, Any], _seen: frozenset[str] | None = None) -> Any:
    seen = _seen or frozenset()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in seen:
                return {"$ref": ref, "__cycle__": True}
            target: Any = spec
            for part in ref.lstrip("#/").split("/"):
                if not isinstance(target, dict) or part not in target:
                    return node
                target = target[part]
            return resolve_refs(target, spec, seen | {ref})
        return {key: resolve_refs(value, spec, seen) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_refs(item, spec, seen) for item in node]
    return node


def request_stream(
    method: str,
    path_or_url: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    query: dict[str, Any] | None = None,
) -> None:
    url = resolve_request_url(path_or_url)

    if query:
        clean_query = {key: str(value) for key, value in query.items() if value is not None}
        if clean_query:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(clean_query)}"

    request_headers = {"Accept": "text/event-stream"}
    if headers:
        for key, value in headers.items():
            if key.lower() != "accept":
                request_headers[key] = value

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=request_headers, method=method.upper())
    started = time.time()
    try:
        with _urlopen(req, timeout=600) as response:
            for raw_line in response:
                sys.stdout.write(raw_line.decode("utf-8", errors="replace"))
                sys.stdout.flush()
            _audit(method, url, started, response.status, _request_id_from(response.headers, None))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        _audit(method, url, started, exc.code, _request_id_from(exc.headers, detail), error=str(exc.reason))
        raise SystemExit(json_dumps({
            "error": {
                "status": exc.code,
                "reason": exc.reason,
                "body": detail,
            }
        })) from exc
    except urllib.error.URLError as exc:
        _audit(method, url, started, None, None, error=str(exc.reason))
        raise SystemExit(format_url_error(exc)) from exc


def _expect_device_login_start_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SystemExit("Device-login start failed: expected a JSON object response")
    required = (
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise SystemExit(
            "Device-login start failed: missing response fields "
            + ", ".join(missing)
        )
    return payload


def _poll_device_login(device_code: str) -> dict[str, Any]:
    response = request_json(
        "POST",
        "/v1/auth/device-logins/tokens",
        body={"device_code": device_code},
    )
    if "status" not in response:
        raise SystemExit("Device-login poll failed: missing response field status")
    return response


def _normalize_poll_interval(value: Any) -> int:
    if not isinstance(value, int) or value <= 0:
        return 5
    return value


def store_device_login_credential(credential: str, profile_name: str | None) -> pathlib.Path:
    normalized = normalize_device_login_credential(credential)
    if not normalized:
        raise SystemExit("Device-login poll failed: credential was empty")
    path = active_config_path() or home_config_path()
    file_config = read_config_from_path(path)
    root_values = dict(file_config.get("values", {}))
    profiles = {
        name: dict(profile)
        for name, profile in file_config.get("profiles", {}).items()
    }

    if profile_name:
        target = dict(profiles.get(profile_name, {}))
        target["SUM_API_BASE_URL"] = base_url()
        target[DEVICE_LOGIN_CREDENTIAL_KEY] = normalized
        profiles[profile_name] = target
        root_values[ACTIVE_PROFILE_KEY] = profile_name
    else:
        root_values["SUM_API_BASE_URL"] = base_url()
        root_values[DEVICE_LOGIN_CREDENTIAL_KEY] = normalized

    write_config_file(path, root_values, profiles)
    return path


def stored_device_login_credential(profile_name: str | None) -> str | None:
    if profile_name:
        return normalize_device_login_credential(config_profiles().get(profile_name, {}).get(DEVICE_LOGIN_CREDENTIAL_KEY))
    return device_login_credential()


def clear_device_login_credential(profile_name: str | None) -> tuple[pathlib.Path, bool]:
    path = active_config_path() or home_config_path()
    file_config = read_config_from_path(path)
    root_values = dict(file_config.get("values", {}))
    profiles = {
        name: dict(profile)
        for name, profile in file_config.get("profiles", {}).items()
    }

    removed = False
    if profile_name:
        target = dict(profiles.get(profile_name, {}))
        if DEVICE_LOGIN_CREDENTIAL_KEY in target:
            removed = True
            del target[DEVICE_LOGIN_CREDENTIAL_KEY]
        if profile_name in profiles:
            profiles[profile_name] = target
    else:
        if DEVICE_LOGIN_CREDENTIAL_KEY in root_values:
            removed = True
            del root_values[DEVICE_LOGIN_CREDENTIAL_KEY]

    write_config_file(path, root_values, profiles)
    return path, removed


def revoke_device_login_credential(credential: str) -> bool:
    response = request_json(
        "POST",
        "/v1/auth/device-logins/revoke",
        headers={"Authorization": f"Bearer {credential}"},
    )
    if not isinstance(response, dict) or "success" not in response:
        raise SystemExit("Device-login logout failed: missing response field success")
    success = response["success"]
    if not isinstance(success, bool):
        raise SystemExit("Device-login logout failed: response field success must be a boolean")
    return success


def iter_operations(spec: dict[str, Any]):
    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(operation, dict):
                continue
            yield method.upper(), path, operation


def command_openapi(_: argparse.Namespace) -> None:
    print(json_dumps(fetch_openapi()))


def command_operations(args: argparse.Namespace) -> None:
    spec = fetch_openapi()
    needle = (args.search or "").lower()
    rows = []
    for method, path, operation in iter_operations(spec):
        haystack = " ".join([
            method,
            path,
            str(operation.get("operationId", "")),
            str(operation.get("summary", "")),
            " ".join(operation.get("tags", [])),
        ]).lower()
        if needle and needle not in haystack:
            continue
        rows.append({
            "method": method,
            "path": path,
            "operation_id": operation.get("operationId"),
            "tags": operation.get("tags", []),
            "summary": operation.get("summary"),
        })
    print(json_dumps(rows))


def find_operation(spec: dict[str, Any], operation_id: str) -> tuple[str, str, dict[str, Any]]:
    for method, path, operation in iter_operations(spec):
        if operation.get("operationId") == operation_id:
            return method, path, operation
    raise SystemExit(f"Operation not found: {operation_id}")


def resolve_operation(
    spec: dict[str, Any],
    candidate_ids: tuple[str, ...] = (),
    *,
    keywords: tuple[str, ...] = (),
    method: str = "GET",
    collection_only: bool = True,
) -> tuple[str, str, dict[str, Any]] | None:
    """Resolve a live (method, path, operation) from the contract by intent, so callers
    never hardcode a path. Tries known operationIds first (precise); falls back to a
    keyword match over operationId/summary/tags (survives an operationId rename). Returns
    None if nothing matches, so the caller can fall back to a documented default."""
    by_id = {op.get("operationId"): (m, p, op) for m, p, op in iter_operations(spec)}
    for cid in candidate_ids:
        if cid in by_id:
            return by_id[cid]
    if keywords:
        for m, p, op in iter_operations(spec):
            if m != method.upper():
                continue
            if collection_only and "{" in p:
                continue
            haystack = " ".join([
                p, str(op.get("operationId", "")), str(op.get("summary", "")),
                " ".join(op.get("tags", [])),
            ]).lower()
            if all(kw in haystack for kw in keywords):
                return m, p, op
    return None


def fill_path(path: str, params: dict[str, Any]) -> str:
    filled = path
    for key, value in params.items():
        filled = filled.replace("{" + key + "}", urllib.parse.quote(str(value), safe=""))
    if "{" in filled or "}" in filled:
        raise SystemExit(f"Missing path parameter for {filled}")
    return filled


def operation_query_params(operation: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    query = {}
    for parameter in operation.get("parameters", []):
        if not isinstance(parameter, dict):
            continue
        if parameter.get("in") != "query":
            continue
        name = parameter.get("name")
        if name in params:
            query[name] = params[name]
    return query


def command_operation(args: argparse.Namespace) -> None:
    spec = fetch_openapi()
    method, path, operation = find_operation(spec, args.operation_id)
    params = parse_json_arg(args.params, {})
    body = parse_json_arg(args.body, None)
    filled_path = fill_path(path, params)
    query = operation_query_params(operation, params)
    if args.stream:
        request_stream(method, filled_path, headers=auth_headers(), body=body, query=query)
        return
    response = request_json(
        method,
        filled_path,
        headers=auth_headers(),
        body=body,
        query=query,
    )
    print(json_dumps(response))


def request_download(method: str, path_or_url: str, output: pathlib.Path, *, headers: dict[str, str] | None = None, query: dict[str, Any] | None = None) -> int:
    url = resolve_request_url(path_or_url)
    if query:
        clean_query = {key: str(value) for key, value in query.items() if value is not None}
        if clean_query:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(clean_query)}"
    request_headers = dict(headers or {})
    req = urllib.request.Request(url, headers=request_headers, method=method.upper())
    started = time.time()
    try:
        with _urlopen(req, timeout=120) as response:
            raw = response.read()
            _audit(method, url, started, response.status, _request_id_from(response.headers, None))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _audit(method, url, started, exc.code, _request_id_from(exc.headers, None), error=str(exc.reason))
        raise SystemExit(json_dumps({"error": {"status": exc.code, "reason": exc.reason, "body": detail}})) from exc
    except urllib.error.URLError as exc:
        _audit(method, url, started, None, None, error=str(exc.reason))
        raise SystemExit(format_url_error(exc)) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    return len(raw)


def command_call(args: argparse.Namespace) -> None:
    query = parse_json_arg(args.query, {})
    if args.body and args.body_file:
        raise SystemExit("Use --body or --body-file, not both")
    if args.body_file:
        # Secrets-safe body transport: contents never appear in argv or transcripts.
        body_path = pathlib.Path(args.body_file).expanduser()
        body = parse_json_arg(body_path.read_text(encoding="utf-8"), None)
    else:
        body = parse_json_arg(args.body, None)
    if args.output:
        if body is not None:
            raise SystemExit("--output supports body-less requests (byte downloads) only")
        output = pathlib.Path(args.output).expanduser()
        size = request_download(args.method, args.path, output, headers=auth_headers(), query=query)
        print(json_dumps({"saved": str(output), "bytes": size}))
        return
    if args.stream:
        request_stream(
            args.method,
            args.path,
            headers=auth_headers(),
            body=body,
            query=query,
        )
        return
    response = request_json(
        args.method,
        args.path,
        headers=auth_headers(),
        body=body,
        query=query,
    )
    print(json_dumps(response))


def command_describe(args: argparse.Namespace) -> None:
    spec = fetch_openapi()
    method, path, operation = find_operation(spec, args.operation_id)
    request_body = operation.get("requestBody")
    out = {
        "method": method,
        "path": path,
        "operationId": operation.get("operationId"),
        "summary": operation.get("summary"),
        "description": operation.get("description"),
        "tags": operation.get("tags", []),
        "parameters": resolve_refs(operation.get("parameters", []), spec),
        "requestBody": resolve_refs(request_body, spec) if request_body else None,
        "responses": resolve_refs(operation.get("responses", {}), spec),
    }
    print(json_dumps(out))


def command_schema(args: argparse.Namespace) -> None:
    spec = fetch_openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    name = args.name
    if name not in schemas:
        matches = [n for n in schemas if name.lower() in n.lower()]
        if not matches:
            raise SystemExit(f"Schema not found: {name}")
        if len(matches) > 1:
            raise SystemExit(
                f"Ambiguous schema name '{name}'. Candidates: {', '.join(sorted(matches)[:10])}"
            )
        name = matches[0]
    print(json_dumps({"name": name, "schema": resolve_refs(schemas[name], spec)}))


def command_token(_: argparse.Namespace) -> None:
    print(json_dumps({"access_token": exchange_m2m_token()}))


def command_login(args: argparse.Namespace) -> None:
    response = _expect_device_login_start_response(
        request_json(
            "POST",
            "/v1/auth/device-logins",
            body={"surface": device_login_server_surface(args.surface)},
        )
    )
    expires_in = response["expires_in"]
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise SystemExit("Device-login start failed: expires_in must be a positive integer")
    interval = _normalize_poll_interval(response.get("interval"))
    profile_name = args.profile or selected_profile_name()
    store_pending_device_login(
        profile_name=profile_name,
        surface=args.surface,
        device_code=response["device_code"],
        interval=interval,
        expires_in=expires_in,
    )
    result = {
        "profile": profile_name,
        "verification_uri_complete": response["verification_uri_complete"],
        "user_code": response["user_code"],
        "expires_in": expires_in,
    }
    print(json_dumps(result))


DEFAULT_LOGIN_POLL_WINDOW_SECONDS = 45


def command_login_poll(args: argparse.Namespace) -> None:
    profile_name = args.profile or selected_profile_name()
    _, pending_state = load_pending_device_login(profile_name)
    device_code = pending_state.get("device_code")
    interval = pending_state.get("interval")
    pending_state_base_url = pending_state.get("base_url")
    expires_at = pending_state.get("expires_at")

    if not isinstance(device_code, str) or not device_code:
        raise SystemExit("Device-login poll failed: pending state is missing device_code")
    if not isinstance(interval, int) or interval <= 0:
        raise SystemExit("Device-login poll failed: pending state is missing interval")
    if not isinstance(pending_state_base_url, str) or not pending_state_base_url:
        raise SystemExit("Device-login poll failed: pending state is missing base_url")
    if not isinstance(expires_at, (int, float)):
        raise SystemExit("Device-login poll failed: pending state is missing expires_at")

    expires_in = int(expires_at - time.time())
    if expires_in <= 0:
        clear_pending_device_login(profile_name, pending_state_base_url)
        print(json_dumps({"status": "expired"}))
        return

    global BASE_URL_OVERRIDE
    BASE_URL_OVERRIDE = pending_state_base_url.rstrip("/")

    # Bounded poll: check for up to `--timeout` seconds, then return control so the caller
    # (the signin skill / model) stays responsive and can re-surface the approval link. A
    # "pending" return means "not approved yet — poll again"; it is NOT device-login expiry.
    # The old unbounded `while True` blocked the whole turn for up to 10 minutes, which buried
    # the approval link and could hit the shell timeout.
    poll_window = max(1, min(args.timeout, expires_in))
    deadline = time.monotonic() + poll_window
    while True:
        response = _poll_device_login(device_code)
        status = response["status"].lower()

        if status == "approved":
            credential = response.get("credential")
            if not isinstance(credential, str) or not credential:
                raise SystemExit("Device-login poll failed: approved response missing credential")
            path = store_device_login_credential(credential, profile_name)
            clear_pending_device_login(profile_name, pending_state_base_url)
            print(json_dumps({
                "status": "approved",
                "config_file": str(path),
                "config_file_mode": config_file_mode(path),
                "profile": profile_name,
            }))
            return

        if status in {"denied", "expired"}:
            clear_pending_device_login(profile_name, pending_state_base_url)
            print(json_dumps({"status": status}))
            return

        if status != "pending":
            raise SystemExit(f"Device-login poll failed: unexpected status '{response['status']}'")

        # Still pending. If the device login itself has expired, report that and stop.
        if time.time() >= expires_at:
            clear_pending_device_login(profile_name, pending_state_base_url)
            print(json_dumps({"status": "expired"}))
            return

        # This bounded window is used up but the login is still valid: hand back a
        # non-terminal "pending" so the caller polls again without hanging the turn.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(json_dumps({
                "status": "pending",
                "expires_in": max(0, int(expires_at - time.time())),
            }))
            return

        time.sleep(min(interval, remaining))


def command_logout(args: argparse.Namespace) -> None:
    profile_name = args.profile or selected_profile_name()
    credential = stored_device_login_credential(profile_name)
    if not credential:
        print(json_dumps({
            "status": "already_logged_out",
            "profile": profile_name,
        }))
        return
    revoked = revoke_device_login_credential(credential)
    if not revoked:
        raise SystemExit("Device-login logout failed: revoke returned success=false")
    path, removed = clear_device_login_credential(profile_name)
    clear_pending_device_login(profile_name, base_url())
    print(json_dumps({
        "status": "logged_out" if removed else "already_logged_out",
        "config_file": str(path),
        "config_file_mode": config_file_mode(path),
        "profile": profile_name,
    }))


def config_file_mode(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    return oct(path.stat().st_mode & 0o777)


def prompt_if_needed(label: str, current: str | None, *, secret: bool = False) -> str | None:
    if current:
        return current
    if not sys.stdin.isatty():
        return current
    prompt = f"{label}: "
    return getpass.getpass(prompt) if secret else input(prompt)


def redacted_values(values: dict[str, str]) -> dict[str, str]:
    redacted = {}
    for key, value in values.items():
        if "SECRET" in key or "TOKEN" in key or "CREDENTIAL" in key:
            redacted[key] = "[redacted]" if value else ""
        else:
            redacted[key] = value
    return redacted


def render_config(values: dict[str, str], profiles: dict[str, dict[str, str]]) -> str:
    lines = ["# Summation local API config. Do not commit this file."]
    for key in sorted(values):
        lines.append(f"{key}={values[key]}")
    for profile in sorted(profiles):
        if lines[-1] != "":
            lines.append("")
        lines.append(f"[profile.{profile}]")
        for key in sorted(profiles[profile]):
            lines.append(f"{key}={profiles[profile][key]}")
    return "\n".join(lines) + "\n"


def write_config_file(
    path: pathlib.Path,
    values: dict[str, str],
    profiles: dict[str, dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config(values, profiles), encoding="utf-8")
    os.chmod(path, 0o600)


def mcp_url() -> str:
    # MCP host tracks the selected environment; allowlisted by construction.
    return ALLOWED_ENVIRONMENTS[selected_env()]["mcp"]


def _claude_binary() -> str:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        raise SystemExit("claude CLI not found on PATH; cannot manage the Summation MCP server registration.")
    return claude_bin


def device_login_server_surface(surface: str) -> str:
    return DEVICE_LOGIN_SURFACE_ALIASES.get(surface, surface)


# --- Codex client: register the MCP server by editing ~/.codex/config.toml ---
# Codex has no `mcp add --header` CLI, so the plugin writes the server block directly.
# This is the Codex parallel of the Claude `claude mcp add --header` path below.
def codex_config_path() -> pathlib.Path:
    codex_home = pathlib.Path(os.getenv("CODEX_HOME", pathlib.Path.home() / ".codex")).expanduser()
    return codex_home / "config.toml"


def toml_string(value: str) -> str:
    # Safe for the constrained values here (credential + URL carry no TOML-special chars).
    return json.dumps(value)


def is_toml_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def toml_table_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return stripped[2:-2].strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1].strip()
    return None


def replace_toml_table(content: str, table_name: str, block: str) -> str:
    lines = content.splitlines()
    out: list[str] = []
    replaced = False
    header = f"[{table_name}]"
    index = 0
    while index < len(lines):
        if lines[index].strip() == header:
            if out and out[-1].strip():
                out.append("")
            out.extend(block.splitlines())
            replaced = True
            index += 1
            while index < len(lines) and not is_toml_table_header(lines[index]):
                index += 1
            if index < len(lines) and out and out[-1].strip():
                out.append("")
            continue
        out.append(lines[index])
        index += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.extend(block.splitlines())
    return "\n".join(out).rstrip() + "\n"


def remove_toml_table_family(content: str, table_name: str) -> tuple[str, bool]:
    lines = content.splitlines()
    out: list[str] = []
    removed = False
    index = 0
    while index < len(lines):
        current_table = toml_table_name(lines[index])
        if current_table == table_name or (
            current_table is not None and current_table.startswith(f"{table_name}.")
        ):
            removed = True
            index += 1
            while index < len(lines) and not is_toml_table_header(lines[index]):
                index += 1
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out).rstrip() + ("\n" if out else ""), removed


def write_codex_config(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def command_codex_mcp_connect() -> None:
    credential = device_login_credential()
    if not credential:
        raise SystemExit("No device-login credential found. Run login first, then mcp-connect.")
    path = codex_config_path()
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    block = "\n".join([
        f"[mcp_servers.{MCP_SERVER_NAME}]",
        f"url = {toml_string(mcp_url())}",
        f"http_headers = {{ \"Authorization\" = {toml_string(f'Bearer {credential}')} }}",
        "enabled = true",
    ])
    write_codex_config(path, replace_toml_table(content, f"mcp_servers.{MCP_SERVER_NAME}", block))
    print(json_dumps({
        "status": "connected",
        "client": "codex",
        "server": MCP_SERVER_NAME,
        "url": mcp_url(),
        "config_file": str(path),
        "config_file_mode": config_file_mode(path),
        "note": "Start a new Codex thread or restart Codex to load the Summation tools.",
    }))


def command_codex_mcp_disconnect() -> None:
    path = codex_config_path()
    if not path.exists():
        print(json_dumps({
            "status": "not_registered",
            "client": "codex",
            "server": MCP_SERVER_NAME,
            "config_file": str(path),
        }))
        return
    content = path.read_text(encoding="utf-8")
    next_content, removed = remove_toml_table_family(content, f"mcp_servers.{MCP_SERVER_NAME}")
    if removed:
        write_codex_config(path, next_content)
    print(json_dumps({
        "status": "disconnected" if removed else "not_registered",
        "client": "codex",
        "server": MCP_SERVER_NAME,
        "config_file": str(path),
        "config_file_mode": config_file_mode(path),
    }))


def command_mcp_connect(args: argparse.Namespace) -> None:
    if getattr(args, "client", "claude") == "codex":
        command_codex_mcp_connect()
        return
    # Register the hosted Summation MCP server with Claude Code, passing the stored
    # device-login credential as a bearer header. The credential moves process-to-process
    # via argv (no shell, no stdout), so it never appears in the conversation.
    credential = device_login_credential()
    if not credential:
        raise SystemExit("No device-login credential found. Run login first, then mcp-connect.")
    claude_bin = _claude_binary()
    # Re-register idempotently: drop any stale entry (e.g. an expired bearer), then add.
    subprocess.run(
        [claude_bin, "mcp", "remove", "-s", "user", MCP_SERVER_NAME],
        capture_output=True, text=True, check=False,
    )
    result = subprocess.run(
        [
            claude_bin, "mcp", "add", "-s", "user", "--transport", "http",
            MCP_SERVER_NAME, mcp_url(),
            "--header", f"Authorization: Bearer {credential}",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"claude mcp add failed (exit {result.returncode}); run `claude mcp list` to inspect.")
    print(json_dumps({
        "status": "connected",
        "server": MCP_SERVER_NAME,
        "url": mcp_url(),
        "scope": "user",
        "note": "Restart Claude Code (or run /mcp) to load the Summation tools.",
    }))


def command_mcp_disconnect(args: argparse.Namespace) -> None:
    if getattr(args, "client", "claude") == "codex":
        command_codex_mcp_disconnect()
        return
    result = subprocess.run(
        [_claude_binary(), "mcp", "remove", "-s", "user", MCP_SERVER_NAME],
        capture_output=True, text=True, check=False,
    )
    status = "disconnected" if result.returncode == 0 else "not_registered"
    print(json_dumps({"status": status, "server": MCP_SERVER_NAME}))


def command_configure(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.path).expanduser() if args.path else home_config_path()
    file_config = read_config_from_path(path)
    root_values = dict(file_config.get("values", {}))
    profiles = {
        name: dict(profile)
        for name, profile in file_config.get("profiles", {}).items()
    }
    profile_name = args.profile or profile_name_from(root_values, profiles) or selected_profile_name()
    target_values = dict(profiles.get(profile_name, {})) if profile_name else dict(root_values)
    client_id = prompt_if_needed(
        "SUM_API_CLIENT_ID",
        args.client_id or target_values.get("SUM_API_CLIENT_ID") or setting("SUM_API_CLIENT_ID"),
    )
    client_secret = prompt_if_needed(
        "SUM_API_CLIENT_SECRET",
        args.client_secret
        or target_values.get("SUM_API_CLIENT_SECRET")
        or setting("SUM_API_CLIENT_SECRET"),
        secret=True,
    )
    # --env must win over a stored SUM_API_BASE_URL so configure can switch a profile's
    # environment (and remediate a now-disallowed stored host) without hand-editing the file.
    if ENV_OVERRIDE:
        configured_base = base_url()
    elif target_values.get("SUM_API_BASE_URL"):
        configured_base = ALLOWED_ENVIRONMENTS[_env_for_url(target_values["SUM_API_BASE_URL"])]["api"]
    else:
        configured_base = base_url()
    values = {
        "SUM_API_BASE_URL": configured_base,
        "SUM_API_CLIENT_ID": client_id or "",
        "SUM_API_CLIENT_SECRET": client_secret or "",
    }
    if args.scope or target_values.get("SUM_API_M2M_SCOPE") or setting("SUM_API_M2M_SCOPE"):
        values["SUM_API_M2M_SCOPE"] = (
            args.scope
            or target_values.get("SUM_API_M2M_SCOPE")
            or setting("SUM_API_M2M_SCOPE", "")
        )

    missing = [key for key, value in values.items() if key != "SUM_API_M2M_SCOPE" and not value]
    if missing:
        raise SystemExit(f"Missing required config values: {', '.join(missing)}")

    stored_profile = profile_name or args.profile
    if stored_profile:
        profiles[stored_profile] = values
        if args.activate or not root_values.get(ACTIVE_PROFILE_KEY):
            root_values[ACTIVE_PROFILE_KEY] = stored_profile
        stored = sorted(values.keys())
    else:
        root_values.update(values)
        stored = sorted(values.keys())

    write_config_file(path, root_values, profiles)
    print(json_dumps({
        "config_file": str(path),
        "mode": config_file_mode(path),
        "active_profile": root_values.get(ACTIVE_PROFILE_KEY),
        "profile": stored_profile,
        "stored": stored,
    }))


def command_mode(_: argparse.Namespace) -> None:
    """Fast, auth-free: report whether internal features are unlocked and which environments are
    selectable. The signin skill branches on this so external users are never asked about an
    environment or tenant (there is only production for them)."""
    internal = is_internal()
    print(json_dumps({
        "internal": internal,
        "environments": list(ALLOWED_ENVIRONMENTS) if internal else ["prod"],
        "selected_env": selected_env(),
        "base_url": base_url(),
        "mcp_url": mcp_url(),
    }))


def command_doctor(_: argparse.Namespace) -> None:
    spec = fetch_openapi()
    config_path = active_config_path()
    result = {
        "internal": is_internal(),
        "environment": selected_env(),
        "base_url": base_url(),
        "profile": selected_profile_name(),
        "config_file": str(config_path) if config_path else None,
        "config_file_mode": config_file_mode(config_path) if config_path else None,
        "openapi_title": spec.get("info", {}).get("title"),
        "openapi_version": spec.get("info", {}).get("version"),
        "path_count": len(spec.get("paths", {})),
        "preferred_auth_mode": auth_mode(),
        "has_device_login_credential": bool(device_login_credential()),
        "has_access_token": bool(setting("SUM_API_ACCESS_TOKEN")),
        "has_m2m_credentials": bool(setting("SUM_API_CLIENT_ID") and setting("SUM_API_CLIENT_SECRET")),
    }
    print(json_dumps(result))


def command_profiles(_: argparse.Namespace) -> None:
    profiles = config_profiles()
    root_values = config_values()
    selected_values = selected_profile_values()
    print(json_dumps({
        "active_profile": selected_profile_name(),
        "preferred_auth_mode": auth_mode(),
        "config_file": str(active_config_path()) if active_config_path() else None,
        "profiles": [
            {
                "name": name,
                "active": name == selected_profile_name(),
                "auth_mode": auth_mode(values=values),
                "has_device_login_credential": bool(
                    normalize_device_login_credential(values.get(DEVICE_LOGIN_CREDENTIAL_KEY))
                ),
                "has_access_token": bool(values.get("SUM_API_ACCESS_TOKEN")),
                "has_m2m_credentials": bool(
                    values.get("SUM_API_CLIENT_ID") and values.get("SUM_API_CLIENT_SECRET")
                ),
                "settings": redacted_values(values),
            }
            for name, values in sorted(profiles.items())
        ],
        "selected_profile_settings": {
            "auth_mode": auth_mode(values=selected_values, selected_values=root_values),
            "has_device_login_credential": bool(
                normalize_device_login_credential(
                    selected_values.get(DEVICE_LOGIN_CREDENTIAL_KEY)
                    or root_values.get(DEVICE_LOGIN_CREDENTIAL_KEY)
                )
            ),
            "has_access_token": bool(
                selected_values.get("SUM_API_ACCESS_TOKEN") or root_values.get("SUM_API_ACCESS_TOKEN")
            ),
            "has_m2m_credentials": bool(
                (selected_values.get("SUM_API_CLIENT_ID") or root_values.get("SUM_API_CLIENT_ID"))
                and (selected_values.get("SUM_API_CLIENT_SECRET") or root_values.get("SUM_API_CLIENT_SECRET"))
            ),
        },
        "legacy_settings": redacted_values(config_values()),
    }))


def command_use_profile(args: argparse.Namespace) -> None:
    path = pathlib.Path(args.path).expanduser() if args.path else active_config_path()
    if not path:
        path = home_config_path()
    file_config = read_config_from_path(path)
    profiles = {
        name: dict(profile)
        for name, profile in file_config.get("profiles", {}).items()
    }
    if args.profile not in profiles:
        raise SystemExit(f"Profile not found: {args.profile}")
    values = dict(file_config.get("values", {}))
    values[ACTIVE_PROFILE_KEY] = args.profile
    write_config_file(path, values, profiles)
    print(json_dumps({
        "config_file": str(path),
        "mode": config_file_mode(path),
        "active_profile": args.profile,
    }))


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="Named profile from .summation-config")


def add_env_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env",
        choices=tuple(ALLOWED_ENVIRONMENTS),
        help=f"Summation environment (internal only; production unless {ADDISON_INTERNAL_ENV}=1)",
    )


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("entries", "items", "projects", "tables", "views", "connections", "connectors", "datasets", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if key == "data" and isinstance(value, dict):
                nested = _extract_items(value)
                if nested:
                    return nested
    return []


def _payload_total(payload: Any, items: list[Any]) -> int:
    if isinstance(payload, dict):
        total = payload.get("total")
        if isinstance(total, int):
            return total
        # _extract_items also unwraps a nested envelope (e.g. {"data": {"datasets": [...], "total": N}});
        # honor a total carried at that same nesting so paged responses are not undercounted.
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("total"), int):
            return data["total"]
    return len(items)


def _name_of(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("name", "title", "display_name", "displayName", "connectionName", "id", "connectionId"):
            value = item.get(key)
            if value:
                return str(value)
        # Never stringify an unknown record: dicts here can carry hosts,
        # users, and secret reference names (e.g. connection configs).
        return "(unnamed)"
    return str(item)


def command_preflight(_: argparse.Namespace) -> None:
    headers = auth_headers()
    result: dict[str, Any] = {
        "base_url": base_url(),
        "profile": selected_profile_name(),
        "sections": {},
        "errors": {},
    }

    def describe(item: Any) -> str:
        # Connections carry infra config (hosts, users, secret ref names) that must
        # not be passed through wholesale; reduce every item to a one-line summary.
        conn_type = item.get("type") or item.get("connectorType") if isinstance(item, dict) else None
        if conn_type:
            parts = [str(conn_type)]
            if item.get("status"):
                parts.append(str(item["status"]))
            if isinstance(item.get("datasetCount"), int):
                parts.append(f"{item['datasetCount']} datasets")
            return f"{_name_of(item)} ({', '.join(parts)})"
        return _name_of(item)

    # Resolve every route from the live contract, not hardcoded paths. The tuples are
    # (preferred operationIds, keyword fallback, last-resort default path) — so a path
    # move self-heals via the operationId, and an operationId rename self-heals via the
    # keyword match; the default only applies if the contract can't be fetched.
    try:
        spec = fetch_openapi()
    except SystemExit:
        spec = None

    def resolve(candidate_ids: tuple[str, ...], keywords: tuple[str, ...], default_path: str) -> str:
        if spec is not None:
            hit = resolve_operation(spec, candidate_ids, keywords=keywords)
            if hit:
                return hit[1]
        return default_path

    def section(name: str, path: str, *, limit_names: int = 15) -> None:
        try:
            payload = request_json("GET", path, headers=headers)
        except SystemExit as exc:
            result["errors"][name] = str(exc)
            return
        items = _extract_items(payload)
        if items:
            result["sections"][name] = {
                "total": _payload_total(payload, items),
                "names": [describe(item) for item in items[:limit_names]],
            }
        elif name in ("identity", "org"):
            result["sections"][name] = payload
        else:
            result["sections"][name] = {"total": _payload_total(payload, items), "names": []}

    def connections_section(list_path: str) -> None:
        # Attached datasets are the analyzable unit, so count them via each connection's
        # datasets sub-resource (the list payload has no reliable inline count).
        try:
            payload = request_json("GET", list_path, headers=headers)
        except SystemExit as exc:
            result["errors"]["connections"] = str(exc)
            return
        conns = _extract_items(payload)
        datasets_total = 0
        for conn in conns:
            if not isinstance(conn, dict):
                continue
            count = conn.get("datasetCount")
            if not isinstance(count, int):
                cid = conn.get("id") or conn.get("connectionId")
                count = 0
                if cid:
                    try:
                        ds = request_json("GET", f"{list_path.rstrip('/')}/{cid}/datasets", headers=headers)
                        # Respect a pagination `total` when present; len() alone would
                        # undercount a paged response and could wrongly keep Gate 2b blocked.
                        count = _payload_total(ds, _extract_items(ds))
                    except SystemExit:
                        count = 0
            datasets_total += count
        result["sections"]["connections"] = {
            "total": _payload_total(payload, conns),
            "names": [describe(item) for item in conns[:15]],
            "datasets_total": datasets_total,
        }

    section("identity", resolve(("get_current_member", "whoami", "get_me"), (), "/v1/me"))
    section("org", resolve(("get_org", "get_tenant_org"), (), "/v1/tenant/org"))
    section("projects", resolve(("list_projects",), ("project",), "/v1/projects"))
    section("tables", resolve(("list_tables",), ("table",), "/v1/tables"))
    section("views", resolve(("list_views",), ("view",), "/v1/views"))
    connections_section(resolve(("list_data_connections",), ("connection", "data"), "/v1/connections/data"))
    print(json_dumps(result))


def command_audit(args: argparse.Namespace) -> None:
    path = audit_path()
    if not path.exists():
        print(json_dumps({"audit_file": str(path), "lines": []}))
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[-args.tail:]:
        print(line)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summation sum-api helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    openapi_parser = subparsers.add_parser("openapi", help="Fetch the live OpenAPI document")
    add_profile_argument(openapi_parser)
    openapi_parser.set_defaults(func=command_openapi)

    operations_parser = subparsers.add_parser("operations", help="List OpenAPI operations")
    add_profile_argument(operations_parser)
    operations_parser.add_argument("search", nargs="?", help="Filter by method, path, tag, operationId, or summary")
    operations_parser.set_defaults(func=command_operations)

    operation_parser = subparsers.add_parser("operation", help="Call an operation by operationId")
    add_profile_argument(operation_parser)
    operation_parser.add_argument("operation_id")
    operation_parser.add_argument("--params", help="JSON object for path and query parameters")
    operation_parser.add_argument("--body", help="JSON request body")
    operation_parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream response body line-by-line (for SSE or NDJSON endpoints; pair with Monitor in Claude Code)",
    )
    operation_parser.set_defaults(func=command_operation)

    call_parser = subparsers.add_parser("call", help="Call a method and path directly")
    add_profile_argument(call_parser)
    call_parser.add_argument("method")
    call_parser.add_argument("path")
    call_parser.add_argument("--query", help="JSON object of query parameters")
    call_parser.add_argument("--body", help="JSON request body")
    call_parser.add_argument(
        "--body-file",
        help="Read the JSON request body from a file (keeps secrets out of argv and transcripts)",
    )
    call_parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream response body line-by-line (for SSE or NDJSON endpoints; pair with Monitor in Claude Code)",
    )
    call_parser.add_argument(
        "--output",
        help="Write the raw response bytes to this file (for PDF/DOCX exports); body-less GET requests only",
    )
    call_parser.set_defaults(func=command_call)

    describe_parser = subparsers.add_parser(
        "describe",
        help="Print an operation's resolved schema without calling it",
    )
    add_profile_argument(describe_parser)
    describe_parser.add_argument("operation_id")
    describe_parser.set_defaults(func=command_describe)

    schema_parser = subparsers.add_parser(
        "schema",
        help="Print a component schema with $ref's resolved (substring match if name is not exact)",
    )
    add_profile_argument(schema_parser)
    schema_parser.add_argument("name")
    schema_parser.set_defaults(func=command_schema)

    if is_internal():
        token_parser = subparsers.add_parser("token", help="Exchange M2M credentials for an access token")
        add_profile_argument(token_parser)
        token_parser.set_defaults(func=command_token)

    login_parser = subparsers.add_parser(
        "login",
        help="Start device login and print the browser approval instructions",
    )
    add_profile_argument(login_parser)
    add_env_argument(login_parser)
    login_parser.add_argument(
        "--surface",
        required=True,
        choices=DEVICE_LOGIN_ALLOWED_SURFACES,
        help="Client surface identifier for the device-login request",
    )
    login_parser.set_defaults(func=command_login)

    login_poll_parser = subparsers.add_parser(
        "login-poll",
        help="Poll the current device login and store the credential on completion",
    )
    add_profile_argument(login_poll_parser)
    login_poll_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_LOGIN_POLL_WINDOW_SECONDS,
        help="Max seconds to poll in one invocation before returning status 'pending' "
             "so the caller can re-check without hanging the turn (default: %(default)s)",
    )
    login_poll_parser.set_defaults(func=command_login_poll)

    logout_parser = subparsers.add_parser(
        "logout",
        help="Remove the stored device-login credential from the selected profile",
    )
    add_profile_argument(logout_parser)
    logout_parser.set_defaults(func=command_logout)

    mcp_connect_parser = subparsers.add_parser(
        "mcp-connect",
        help="Register the hosted Summation MCP server using the stored credential",
    )
    add_profile_argument(mcp_connect_parser)
    mcp_connect_parser.add_argument(
        "--client", choices=("claude", "codex"), default="claude",
        help="Which client config to register the MCP server with",
    )
    mcp_connect_parser.set_defaults(func=command_mcp_connect)

    mcp_disconnect_parser = subparsers.add_parser(
        "mcp-disconnect",
        help="Remove the Summation MCP server registration",
    )
    mcp_disconnect_parser.add_argument(
        "--client", choices=("claude", "codex"), default="claude",
        help="Which client config to remove the MCP server from",
    )
    mcp_disconnect_parser.set_defaults(func=command_mcp_disconnect)

    if is_internal():
        configure_parser = subparsers.add_parser("configure", help="Write a local Summation config file")
        configure_parser.add_argument("--profile", help="Profile name to create or update")
        configure_parser.add_argument(
            "--activate",
            action="store_true",
            help="Make the written profile active",
        )
        add_env_argument(configure_parser)
        configure_parser.add_argument("--client-id", dest="client_id", help="M2M client ID")
        configure_parser.add_argument("--client-secret", dest="client_secret", help="M2M client secret")
        configure_parser.add_argument("--scope", help="M2M token scope")
        configure_parser.add_argument("--path", help="Config file path")
        configure_parser.set_defaults(func=command_configure)

    preflight_parser = subparsers.add_parser(
        "preflight", help="Authenticated environment summary: identity, org, projects, tables, views, connections"
    )
    add_profile_argument(preflight_parser)
    preflight_parser.set_defaults(func=command_preflight)

    audit_parser = subparsers.add_parser("audit", help="Print recent API audit log lines (~/.summation/audit.jsonl)")
    audit_parser.add_argument("--tail", type=int, default=20, help="Number of trailing lines to print")
    audit_parser.set_defaults(func=command_audit)

    mode_parser = subparsers.add_parser(
        "mode", help="Report internal/external mode and selectable environments (auth-free)"
    )
    mode_parser.set_defaults(func=command_mode)

    doctor_parser = subparsers.add_parser("doctor", help="Check OpenAPI reachability and local auth inputs")
    add_profile_argument(doctor_parser)
    doctor_parser.set_defaults(func=command_doctor)

    if is_internal():
        profiles_parser = subparsers.add_parser("profiles", help="List configured profiles")
        profiles_parser.set_defaults(func=command_profiles)

        use_profile_parser = subparsers.add_parser("use-profile", help="Set the active profile")
        use_profile_parser.add_argument("profile")
        use_profile_parser.add_argument("--path", help="Config file path")
        use_profile_parser.set_defaults(func=command_use_profile)

    args = parser.parse_args()
    global PROFILE_OVERRIDE, ENV_OVERRIDE
    PROFILE_OVERRIDE = getattr(args, "profile", None)
    ENV_OVERRIDE = getattr(args, "env", None)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
