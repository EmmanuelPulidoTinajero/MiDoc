"""Unified CLI E2E runner for MiDoc (4-tier opaque-box suite, Python 3.12+ stdlib)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import unittest
from typing import Any


E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.e2e.harness.browser_driver import playwright_available  # noqa: E402
from tests.e2e.harness.config import (  # noqa: E402
    PreflightError,
    RunConfig,
    build_and_start_context,
    set_active_context,
)


TIER_DIRS = {
    "1": E2E_DIR / "tier1_features",
    "2": E2E_DIR / "tier2_boundaries",
    "3": E2E_DIR / "tier3_pairwise",
    "4": E2E_DIR / "tier4_scenarios",
}


class StructuredTestResult(unittest.TextTestResult):
    def __init__(self, stream: Any, descriptions: bool, verbosity: int) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.records: list[dict[str, Any]] = []
        self._started_at: dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        self._started_at[test.id()] = time.perf_counter()
        super().startTest(test)

    def _finish(self, test: unittest.TestCase, status: str, detail: str | None = None) -> None:
        t0 = self._started_at.pop(test.id(), time.perf_counter())
        rec: dict[str, Any] = {
            "id": test.id(),
            "status": status,
            "durationMs": round((time.perf_counter() - t0) * 1000, 2),
        }
        if detail:
            rec["detail"] = detail
        self.records.append(rec)

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._finish(test, "PASS")

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._finish(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self._finish(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self._finish(test, "SKIP", reason)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MiDoc 4-Tier Opaque-Box E2E Test Runner")
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "all"], default="all")
    parser.add_argument("--target", choices=["local", "cloud"], default="local")
    parser.add_argument("--mode", choices=["auto", "live", "self-test"], default="auto")
    parser.add_argument("--stripe-mode", choices=["mock", "live_cloud"], default=None)
    parser.add_argument("--stripe-mock-port", type=int, default=None, help="Bind StripeMockServer to a deterministic port (or set STRIPE_MOCK_PORT)")
    parser.add_argument("--stripe-mock-url", default=None, help="Attach to an already-running StripeMockServer (or set E2E_STRIPE_MOCK_URL)")
    browser_group = parser.add_mutually_exclusive_group()
    browser_group.add_argument("--with-browser", action="store_true", help="Require Playwright browser checks")
    browser_group.add_argument("--skip-browser", action="store_true", help="Skip Playwright browser UI checks")
    parser.add_argument("--api-url", default=None, help="Explicit backend API base URL")
    parser.add_argument("--frontend-url", default=None, help="Explicit frontend URL")
    parser.add_argument("--report", type=Path, default=None, help="Write structured JSON verdict report")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose unittest output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with_browser = bool(args.with_browser)
    if args.with_browser and not playwright_available():
        print(
            "[FATAL] --with-browser requested, but Playwright is not available in Python environment "
            "or %TEMP%/midoc-playwright.",
            file=sys.stderr,
        )
        return 2

    cfg = RunConfig(
        tier=args.tier,
        target=args.target,
        mode=args.mode,
        stripe_mode=args.stripe_mode,
        stripe_mock_port=args.stripe_mock_port,
        stripe_mock_url=args.stripe_mock_url,
        with_browser=with_browser,
        browser_explicit=bool(args.with_browser or args.skip_browser),
        api_url=args.api_url,
        frontend_url=args.frontend_url,
        report_path=args.report,
        repo_root=REPO_ROOT,
    )

    try:
        ctx = build_and_start_context(cfg)
    except PreflightError as err:
        print(str(err), file=sys.stderr)
        return 2

    set_active_context(ctx)
    if ctx.mode == "self-test":
        print(
            "=== RUNNING IN --mode self-test (CONTRACT FIXTURE SERVER; NOT LIVE BACKEND) ===",
            flush=True,
        )
    else:
        print(
            f"=== RUNNING IN --mode live (target={ctx.target}, stripe={ctx.stripe_mode}, api={ctx.api_url}) ===",
            flush=True,
        )

    t_start = time.perf_counter()
    try:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        selected = ["1", "2", "3", "4"] if args.tier == "all" else [args.tier]
        for t in selected:
            tier_dir = TIER_DIRS[t]
            discovered = loader.discover(
                start_dir=str(tier_dir),
                pattern="test_*.py",
                top_level_dir=str(REPO_ROOT),
            )
            suite.addTests(discovered)

        runner = unittest.TextTestRunner(
            verbosity=2 if args.verbose else 1,
            resultclass=StructuredTestResult,
        )
        result: StructuredTestResult = runner.run(suite)  # type: ignore[assignment]
        elapsed = round(time.perf_counter() - t_start, 3)

        total = result.testsRun
        failed = len(result.failures)
        errors = len(result.errors)
        skipped = len(result.skipped)
        passed = total - failed - errors - skipped

        report_payload = {
            "testedAt": datetime.now(timezone.utc).isoformat(),
            "mode": ctx.mode,
            "target": ctx.target,
            "stripeMode": ctx.stripe_mode,
            "liveVerified": ctx.live_verified,
            "withBrowser": ctx.with_browser,
            "tier": args.tier,
            "apiUrl": ctx.api_url,
            "frontendUrl": ctx.frontend_url,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
                "durationSeconds": elapsed,
            },
            "results": result.records,
        }

        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(
            f"[SUMMARY] mode={ctx.mode} liveVerified={ctx.live_verified} "
            f"total={total} passed={passed} failed={failed} errors={errors} skipped={skipped} "
            f"duration={elapsed}s",
            flush=True,
        )
        if total == 0 or failed > 0 or errors > 0 or (ctx.mode == "live" and skipped > 0):
            return 1
        return 0
    finally:
        set_active_context(None)
        ctx.stop()


if __name__ == "__main__":
    raise SystemExit(main())
