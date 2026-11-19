"""Opaque-box HTTP client & concurrency helpers using Python stdlib only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid


class HttpTransportError(RuntimeError):
    """Raised when the remote HTTP endpoint is unreachable or timed out."""


@dataclass
class ApiResponse:
    status: int
    headers: dict[str, str]
    body_bytes: bytes
    text: str
    json_data: Any

    @property
    def data(self) -> Any:
        if isinstance(self.json_data, dict) and "data" in self.json_data:
            return self.json_data["data"]
        return self.json_data

    @property
    def error(self) -> str | None:
        if isinstance(self.json_data, dict):
            err = self.json_data.get("error")
            if isinstance(err, str):
                return err
            if isinstance(err, dict):
                return str(err.get("message") or err)
        return None


def _decode_response(status: int, headers_obj: Any, raw_bytes: bytes) -> ApiResponse:
    headers = {k.lower(): v for k, v in headers_obj.items()} if headers_obj else {}
    text = raw_bytes.decode("utf-8", errors="replace")
    parsed: Any = None
    if text.strip():
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
    return ApiResponse(
        status=status,
        headers=headers,
        body_bytes=raw_bytes,
        text=text,
        json_data=parsed,
    )


class HttpClient:
    """Stateless REST client communicating exclusively via external HTTP boundaries."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _full_url(self, path: str, query: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            rel = path if path.startswith("/") else f"/{path}"
            url = f"{self.base_url}{rel}"
        if query:
            filtered = {k: v for k, v in query.items() if v is not None}
            if filtered:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{urlencode(filtered)}"
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        raw_bytes: bytes | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ApiResponse:
        url = self._full_url(path, query=query)
        req_headers: dict[str, str] = {"Accept": "application/json"}
        payload: bytes | None = None

        if raw_bytes is not None:
            payload = raw_bytes
        elif body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json; charset=utf-8"

        if token:
            req_headers["Authorization"] = f"Bearer {token}"
        if headers:
            req_headers.update(headers)

        req = Request(url, data=payload, headers=req_headers, method=method.upper())
        try:
            with urlopen(req, timeout=timeout or self.timeout) as resp:
                return _decode_response(resp.status, resp.headers, resp.read())
        except HTTPError as err:
            raw_err = err.read() if err.fp else b""
            return _decode_response(err.code, err.headers, raw_err)
        except (URLError, TimeoutError, OSError) as err:
            raise HttpTransportError(f"{method.upper()} {url} failed: {err}") from err

    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        return self.request("GET", path, token=token, query=query, headers=headers)

    def post(
        self,
        path: str,
        body: Any = None,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        raw_bytes: bytes | None = None,
    ) -> ApiResponse:
        return self.request("POST", path, body=body, raw_bytes=raw_bytes, token=token, headers=headers)

    def put(
        self,
        path: str,
        body: Any = None,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        raw_bytes: bytes | None = None,
    ) -> ApiResponse:
        return self.request("PUT", path, body=body, raw_bytes=raw_bytes, token=token, headers=headers)

    def delete(
        self,
        path: str,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        return self.request("DELETE", path, token=token, headers=headers)

    def options(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> ApiResponse:
        return self.request("OPTIONS", path, headers=headers)

    def upload_presigned_post(
        self,
        url: str,
        fields: dict[str, str],
        filename: str,
        content_type: str,
        data_bytes: bytes,
    ) -> ApiResponse:
        boundary = f"midoc-{uuid.uuid4().hex}"
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
            + data_bytes
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        body = b"".join(chunks)
        return self.request(
            "POST",
            url,
            raw_bytes=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def download_url(self, url: str, headers: dict[str, str] | None = None) -> ApiResponse:
        return self.request("GET", url, headers=headers)

    @staticmethod
    def run_concurrent(callables: list[Callable[[], Any]], max_workers: int = 4) -> list[Any]:
        if not callables:
            return []
        barrier = threading.Barrier(len(callables))

        def _run_with_barrier(fn: Callable[[], Any]) -> Any:
            barrier.wait(timeout=10.0)
            return fn()

        with ThreadPoolExecutor(max_workers=max(max_workers, len(callables))) as pool:
            futures = [pool.submit(_run_with_barrier, fn) for fn in callables]
            return [f.result() for f in futures]
