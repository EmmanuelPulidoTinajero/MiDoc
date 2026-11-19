"""Configuration, strict live/self-test isolation, preflight gate, and runtime lifecycle."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from typing import Any
import uuid

from .http_client import HttpClient, HttpTransportError
from .stripe_mock import ExternalStripeMockClient, StripeMockServer


class PreflightError(RuntimeError):
    """Raised when live target prerequisites or M2 capabilities fail."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_live_preflight(api_url: str, timeout: float = 5.0) -> tuple[bool, list[str]]:
    """
    Verify real target reachability & M2 capability contract strictly over HTTP.
    Handles auth-before-route backends (`401` on unauthenticated calls) by registering
    disposable synthetic probe accounts and verifying route status with valid JWTs.
    NEVER falls back to self-test fixtures.
    """
    client = HttpClient(api_url, timeout=timeout)
    errors: list[str] = []

    # 1. /health liveness
    try:
        health = client.get("/health")
    except HttpTransportError as err:
        return False, [f"GET /health unreachable at {api_url}: {err}"]

    if health.status != 200 or not isinstance(health.json_data, dict) or health.json_data.get("status") != "ok":
        errors.append(f"GET /health expected 200 {{'status':'ok'}}, got {health.status}: {health.text[:200]}")
        return False, errors

    needs_auth_probe = False

    # 2. Unauthenticated probes
    try:
        chk = client.post("/api/subscriptions/checkout", {})
        if chk.status == 404:
            errors.append("POST /api/subscriptions/checkout returned 404 (M2 Stripe checkout not deployed)")
        elif chk.status == 401:
            needs_auth_probe = True
    except HttpTransportError as err:
        errors.append(f"POST /api/subscriptions/checkout failed: {err}")

    try:
        pay = client.post("/api/subscriptions/pay", {})
        if pay.status == 401:
            needs_auth_probe = True
        elif pay.status not in (404, 410):
            errors.append(
                f"POST /api/subscriptions/pay returned HTTP {pay.status} (expected 410/404; "
                "legacy simulated card endpoint is still active)"
            )
    except HttpTransportError as err:
        errors.append(f"POST /api/subscriptions/pay probe failed: {err}")

    for method, path in (
        ("PUT", "/api/me"),
        ("POST", "/api/auth/refresh"),
        ("GET", "/api/records/access-log"),
    ):
        try:
            resp = client.request(method, path, body={} if method != "GET" else None)
            if resp.status == 404:
                errors.append(f"{method} {path} returned 404 (M2 endpoint missing)")
            elif resp.status == 401:
                needs_auth_probe = True
            else:
                errors.append(f"{method} {path} unauthenticated returned {resp.status} (expected 401)")
        except HttpTransportError as err:
            errors.append(f"{method} {path} probe failed: {err}")

    if errors:
        return False, errors

    # 3. Auth-before-route verification using disposable synthetic probe accounts
    if needs_auth_probe:
        probe_tag = uuid.uuid4().hex[:10]
        doc_reg = client.post(
            "/api/auth/register",
            {
                "email": f"preflight-doc-{probe_tag}@example.invalid",
                "password": "PreflightPass2026!9",
                "role": "DOCTOR",
                "name": "Dr. Preflight",
                "specialty": "General",
                "location": "CDMX",
                "price": 500,
                "durationMin": 30,
            },
        )
        if doc_reg.status != 201 or not isinstance(doc_reg.json_data, dict) or not doc_reg.json_data.get("token"):
            errors.append(
                f"Authenticated preflight failed registering disposable doctor ({doc_reg.status}): {doc_reg.text[:200]}"
            )
            return False, errors
        doc_tok = doc_reg.json_data["token"]

        pat_reg = client.post(
            "/api/auth/register",
            {
                "email": f"preflight-pat-{probe_tag}@example.invalid",
                "password": "PreflightPass2026!9",
                "role": "PACIENTE",
                "name": "Paciente Preflight",
            },
        )
        if pat_reg.status != 201 or not isinstance(pat_reg.json_data, dict) or not pat_reg.json_data.get("token"):
            errors.append(
                f"Authenticated preflight failed registering disposable patient ({pat_reg.status}): {pat_reg.text[:200]}"
            )
            return False, errors
        pat_tok = pat_reg.json_data["token"]

        pay_auth = client.post("/api/subscriptions/pay", {}, token=doc_tok)
        if pay_auth.status not in (404, 410):
            errors.append(
                f"Authenticated POST /api/subscriptions/pay returned HTTP {pay_auth.status} "
                "(expected 410/404; legacy simulated card endpoint is still active)"
            )

        chk_auth = client.post("/api/subscriptions/checkout", {"successUrl": "javascript:bad"}, token=doc_tok)
        if chk_auth.status == 404:
            errors.append("Authenticated POST /api/subscriptions/checkout returned 404 (M2 Stripe checkout missing)")

        me_auth = client.put("/api/me", {}, token=doc_tok)
        if me_auth.status == 404:
            errors.append("Authenticated PUT /api/me returned 404 (M2 profile update endpoint missing)")

        ref_auth = client.post("/api/auth/refresh", {}, token=doc_tok)
        if ref_auth.status == 404:
            errors.append("Authenticated POST /api/auth/refresh returned 404 (M2 refresh endpoint missing)")

        log_auth = client.get("/api/records/access-log", token=pat_tok)
        if log_auth.status == 404:
            errors.append("Authenticated GET /api/records/access-log returned 404 (M2 access-log endpoint missing)")

    return len(errors) == 0, errors


def _wait_for_health(api_url: str, max_wait_s: float = 10.0) -> bool:
    client = HttpClient(api_url, timeout=2.0)
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        try:
            resp = client.get("/health")
            if resp.status == 200:
                return True
        except HttpTransportError:
            pass
        time.sleep(0.15)
    return False


@dataclass
class RunConfig:
    tier: str = "all"
    target: str = "local"
    mode: str = "auto"
    stripe_mode: str | None = None
    stripe_mock_port: int | None = None
    stripe_mock_url: str | None = None
    with_browser: bool = False
    browser_explicit: bool = False
    api_url: str | None = None
    frontend_url: str | None = None
    report_path: Path | None = None
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[3])
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))
    project_name: str = field(default_factory=lambda: os.environ.get("MIDOC_PROJECT_NAME", "midoc"))


@dataclass
class ActiveContext:
    mode: str  # "live" | "self-test"
    target: str  # "local" | "cloud"
    stripe_mode: str  # "mock" | "live_cloud"
    live_verified: bool
    api_url: str
    frontend_url: str | None
    with_browser: bool
    repo_root: Path
    aws_region: str
    project_name: str
    stripe_mock: StripeMockServer | ExternalStripeMockClient | None = None
    self_test_server: Any = None
    use_self_test_fixtures: bool = False
    _spawned_local_proc: subprocess.Popen[bytes] | None = None
    _cloud_outputs: dict[str, Any] = field(default_factory=dict)

    def client(self, timeout: float = 15.0) -> HttpClient:
        return HttpClient(self.api_url, timeout=timeout)

    def stop(self) -> None:
        if self._spawned_local_proc is not None:
            try:
                self._spawned_local_proc.terminate()
                self._spawned_local_proc.wait(timeout=5.0)
            except Exception:
                try:
                    self._spawned_local_proc.kill()
                except Exception:
                    pass
            self._spawned_local_proc = None
        if self.self_test_server is not None:
            self.self_test_server.stop()
            self.self_test_server = None
        if self.stripe_mock is not None:
            self.stripe_mock.stop()
            self.stripe_mock = None


_ACTIVE_CONTEXT: ActiveContext | None = None


def set_active_context(ctx: ActiveContext | None) -> None:
    global _ACTIVE_CONTEXT
    _ACTIVE_CONTEXT = ctx


def get_active_context() -> ActiveContext:
    if _ACTIVE_CONTEXT is None:
        raise RuntimeError(
            "E2E ActiveContext is not initialized. Run via `python tests/e2e/run_e2e.py`."
        )
    return _ACTIVE_CONTEXT


def _discover_terraform_outputs(repo_root: Path) -> dict[str, Any]:
    tf_bin = shutil.which("terraform")
    if not tf_bin:
        return {}
    infra_dir = repo_root / "infrastructure"
    if not infra_dir.exists():
        return {}
    try:
        proc = subprocess.run(
            [tf_bin, f"-chdir={infra_dir}", "output", "-json"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=20.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {}
        raw = json.loads(proc.stdout)
        return {k: v.get("value") for k, v in raw.items() if isinstance(v, dict) and "value" in v}
    except Exception:
        return {}


def _spawn_local_backend(
    repo_root: Path,
    *,
    stripe_base_url: str | None,
    stripe_secret_key: str,
    stripe_webhook_secret: str,
    allow_demo_seed: bool = True,
) -> tuple[subprocess.Popen[bytes], str]:
    local_py = repo_root / "backend" / "src" / "local.py"
    if not local_py.exists():
        raise PreflightError(f"Cannot spawn local backend; missing {local_py}")
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "PORT": str(port),
            "NODE_ENV": "test",
            "JWT_SECRET": "e2e-local-jwt-secret-change-in-prod",
            "METRICS_ENABLED": "true",
            "ALLOW_DEMO_SEED": "true" if allow_demo_seed else "false",
            "PAYMENT_MODE": "test",
            "STRIPE_SECRET_KEY": stripe_secret_key,
            "STRIPE_WEBHOOK_SECRET": stripe_webhook_secret,
            "FRONTEND_BASE_URL": "http://127.0.0.1:4200/index.html",
        }
    )
    if stripe_base_url:
        env["STRIPE_API_BASE"] = f"{stripe_base_url.rstrip('/')}/v1"
    proc = subprocess.Popen(
        [sys.executable, str(local_py)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    api_url = f"http://127.0.0.1:{port}"
    if not _wait_for_health(api_url, max_wait_s=10.0):
        proc.terminate()
        raise PreflightError(f"Spawned {local_py} on {api_url} did not become healthy within 10s")
    return proc, api_url


def build_and_start_context(cfg: RunConfig) -> ActiveContext:
    """Resolve mode/target, enforce strict live vs self-test isolation, and run preflight."""
    stripe_mode = cfg.stripe_mode or ("live_cloud" if cfg.target == "cloud" else "mock")
    if cfg.target == "local" and stripe_mode == "live_cloud" and not os.environ.get("STRIPE_SECRET_KEY"):
        raise PreflightError("--stripe-mode live_cloud requires STRIPE_SECRET_KEY in environment")

    api_url = cfg.api_url or os.environ.get("MIDOC_API_URL")
    frontend_url = cfg.frontend_url or os.environ.get("MIDOC_FRONTEND_URL")

    # Resolve auto -> live or self-test (never silently falling back to self-test!)
    if cfg.mode == "self-test":
        resolved_mode = "self-test"
    elif cfg.mode == "live":
        resolved_mode = "live"
    elif cfg.mode == "auto":
        resolved_mode = "live"
    else:
        raise PreflightError(f"Unsupported --mode: {cfg.mode}")

    mock_port = cfg.stripe_mock_port
    if mock_port is None and os.environ.get("STRIPE_MOCK_PORT"):
        try:
            mock_port = int(os.environ["STRIPE_MOCK_PORT"])
        except ValueError as err:
            raise PreflightError(f"Invalid STRIPE_MOCK_PORT: {os.environ['STRIPE_MOCK_PORT']}") from err
    mock_url = cfg.stripe_mock_url or os.environ.get("E2E_STRIPE_MOCK_URL")

    # =========================================================================
    # SELF-TEST PATH (only when explicitly requested via --mode self-test)
    # =========================================================================
    if resolved_mode == "self-test":
        if cfg.target == "cloud":
            raise PreflightError("--mode self-test cannot be used with --target cloud")
        from .self_test_server import SelfTestServer  # lazy import isolated to self-test only

        stripe_mock: StripeMockServer | ExternalStripeMockClient | None = None
        if stripe_mode == "mock":
            if mock_url:
                stripe_mock = ExternalStripeMockClient(
                    mock_url,
                    secret_key=os.environ.get("STRIPE_SECRET_KEY", "sk_test_midoc_mock_0000000000000000"),
                    webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_midoc_mock_0000000000000000"),
                )
            else:
                stripe_mock = StripeMockServer(port=mock_port or 0).start()
        st_server = SelfTestServer(
            stripe_base_url=stripe_mock.base_url if stripe_mock else "https://api.stripe.com",
            stripe_secret_key=stripe_mock.secret_key if stripe_mock else os.environ.get("STRIPE_SECRET_KEY", "sk_test_0"),
            stripe_webhook_secret=(
                stripe_mock.webhook_secret if stripe_mock else os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_0")
            ),
        ).start()
        return ActiveContext(
            mode="self-test",
            target="local",
            stripe_mode=stripe_mode,
            live_verified=False,
            api_url=st_server.base_url,
            frontend_url=f"{st_server.base_url}/index.html",
            with_browser=cfg.with_browser,
            repo_root=cfg.repo_root,
            aws_region=cfg.aws_region,
            project_name=cfg.project_name,
            stripe_mock=stripe_mock,
            self_test_server=st_server,
            use_self_test_fixtures=True,
        )

    # =========================================================================
    # LIVE PATH (STRICTLY ZERO IMPORT/FALLBACK TO self_test_server/fixtures)
    # =========================================================================
    cloud_outputs: dict[str, Any] = {}
    if cfg.target == "cloud":
        cloud_outputs = _discover_terraform_outputs(cfg.repo_root)
        api_url = api_url or cloud_outputs.get("api_url")
        frontend_url = frontend_url or cloud_outputs.get("frontend_url")
        if not api_url:
            raise PreflightError(
                "[mode=live][target=cloud] MIDOC_API_URL is not set and Terraform `api_url` output is unavailable."
            )
        if not api_url.startswith("https://"):
            raise PreflightError(f"[mode=live][target=cloud] API URL must use https://, got: {api_url}")
        if cfg.with_browser and (not frontend_url or not frontend_url.startswith("https://")):
            raise PreflightError(
                f"[mode=live][target=cloud] --with-browser requires HTTPS MIDOC_FRONTEND_URL, got: {frontend_url}"
            )
        aws_bin = shutil.which("aws")
        if not aws_bin:
            raise PreflightError("[mode=live][target=cloud] AWS CLI (`aws`) not found in PATH")
        sts = subprocess.run(
            [aws_bin, "sts", "get-caller-identity", "--region", cfg.aws_region, "--output", "json"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=15.0,
        )
        if sts.returncode != 0:
            raise PreflightError(
                f"[mode=live][target=cloud] AWS CLI authentication failed: {sts.stderr.strip()}"
            )

    stripe_mock = None
    spawned_proc: subprocess.Popen[bytes] | None = None
    try:
        if stripe_mode == "mock" and cfg.target == "local":
            if mock_url:
                stripe_mock = ExternalStripeMockClient(
                    mock_url,
                    secret_key=os.environ.get("STRIPE_SECRET_KEY", "sk_test_midoc_mock_0000000000000000"),
                    webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_midoc_mock_0000000000000000"),
                )
            else:
                stripe_mock = StripeMockServer(port=mock_port or 0).start()

        if cfg.target == "local" and not api_url:
            spawned_proc, api_url = _spawn_local_backend(
                cfg.repo_root,
                stripe_base_url=stripe_mock.base_url if stripe_mock else None,
                stripe_secret_key=stripe_mock.secret_key
                if stripe_mock
                else os.environ.get("STRIPE_SECRET_KEY", "sk_test_live"),
                stripe_webhook_secret=stripe_mock.webhook_secret
                if stripe_mock
                else os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_live"),
            )

        assert api_url is not None
        ok, errs = run_live_preflight(api_url)
        if not ok:
            hint = ""
            if cfg.mode == "auto" and cfg.target == "local" and not (cfg.api_url or os.environ.get("MIDOC_API_URL")):
                hint = (
                    "\nHint: Current backend/src/local.py failed live preflight. "
                    "Pass `--mode self-test` to validate the E2E suite against the contract fixture server."
                )
            raise PreflightError(
                f"[FATAL][mode={cfg.mode}][target={cfg.target}] Live capability preflight failed at {api_url}:\n"
                + "\n".join(f"  - {e}" for e in errs)
                + hint
            )

        ctx = ActiveContext(
            mode="live",
            target=cfg.target,
            stripe_mode=stripe_mode,
            live_verified=True,
            api_url=api_url,
            frontend_url=frontend_url,
            with_browser=cfg.with_browser,
            repo_root=cfg.repo_root,
            aws_region=cfg.aws_region,
            project_name=cfg.project_name,
            stripe_mock=stripe_mock,
            self_test_server=None,
            use_self_test_fixtures=False,
            _spawned_local_proc=spawned_proc,
            _cloud_outputs=cloud_outputs,
        )
        assert ctx.self_test_server is None and not ctx.use_self_test_fixtures
        return ctx
    except Exception:
        if spawned_proc is not None:
            try:
                spawned_proc.terminate()
                spawned_proc.wait(timeout=3.0)
            except Exception:
                pass
        if stripe_mock is not None:
            stripe_mock.stop()
        raise
