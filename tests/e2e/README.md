# MiDoc 4-Tier Opaque-Box E2E Test Suite (`tests/e2e/`)

Pure Python 3.12+ stdlib (`unittest`, `urllib.request`, `http.server.ThreadingHTTPServer`, `subprocess`, `pathlib`) end-to-end verification suite covering all 17 feature groups (`F01`–`F17`) across 4 tiers (**197 tests total**):

- **Tier 1 (`tier1_features/`):** 85 isolated feature happy-path tests (`5` per `F01`–`F17`)
- **Tier 2 (`tier2_boundaries/`):** 85 boundary, negative, security & viewport tests (`5` per `F01`–`F17`)
- **Tier 3 (`tier3_pairwise/`):** 18 cross-feature pairwise combination tests
- **Tier 4 (`tier4_scenarios/`):** 9 multi-actor end-to-end application journeys

---

## 1. `--mode self-test` (Contract Fixture Server)

Validates the E2E suite itself against the in-harness contract fixture server (`harness/self_test_server.py`) and mock Stripe server (`harness/stripe_mock.py`). Produces `"liveVerified": false` in the JSON report and **never** masquerades as a live backend.

```bash
python tests/e2e/run_e2e.py --mode self-test --tier all --report /tmp/e2e-selftest.json
```

Run individual tiers:

```bash
python tests/e2e/run_e2e.py --mode self-test --tier 1
python tests/e2e/run_e2e.py --mode self-test --tier 2
python tests/e2e/run_e2e.py --mode self-test --tier 3
python tests/e2e/run_e2e.py --mode self-test --tier 4
```

---

## 2. `--mode live --target local` (Real Backend + Mock Stripe)

Targets the real backend (`backend/src/local.py` or explicit `--api-url`) with strict live capability preflight gating (exits with code `2` if unreachable or if M2 Stripe/account/audit endpoints are missing, with zero fallback to self-test):

```bash
python tests/e2e/run_e2e.py --mode live --target local --stripe-mode mock --tier all
```

### External Local Server Coordination (`--api-url` + `--stripe-mode mock`)

If running an external local backend (`--api-url http://127.0.0.1:3000`), coordinate `StripeMockServer` deterministically via `--stripe-mock-port` (or `STRIPE_MOCK_PORT`) or attach to a pre-started mock via `E2E_STRIPE_MOCK_URL` / `--stripe-mock-url`:

```bash
# Terminal 1: Start standalone StripeMockServer on port 4242
python -m tests.e2e.harness.stripe_mock --port 4242

# Terminal 2: Start external backend pointing at the mock
export STRIPE_API_BASE="http://127.0.0.1:4242/v1"
export STRIPE_SECRET_KEY="sk_test_midoc_mock_0000000000000000"
export STRIPE_WEBHOOK_SECRET="whsec_midoc_mock_0000000000000000"
python backend/src/local.py

# Terminal 3: Attach E2E runner to both external servers
export E2E_STRIPE_MOCK_URL="http://127.0.0.1:4242"
python tests/e2e/run_e2e.py --mode live --target local --api-url http://127.0.0.1:3000 --stripe-mode mock --tier all
```

Or pass `--stripe-mock-port 4242` directly to `run_e2e.py` so the runner binds port `4242` for the external backend.

Optional Playwright browser checks (requires `playwright` in Python env or `%TEMP%/midoc-playwright`):

```bash
python tests/e2e/run_e2e.py --mode live --target local --stripe-mode mock --with-browser --frontend-url http://127.0.0.1:4200/index.html --tier all
```

---

## 3. `--mode live --target cloud` (M5 Live AWS Deployment)

Targets live deployed API Gateway + S3 HTTPS frontend + AWS CLI CloudWatch/EventBridge/S3 verification.
For `live_cloud` subscription activation, export `STRIPE_WEBHOOK_SECRET` (from Terraform / Secrets Manager `whsec_...`) or pass `--with-browser`:

```bash
export MIDOC_API_URL="https://<api-id>.execute-api.us-east-1.amazonaws.com"
export MIDOC_FRONTEND_URL="https://<frontend-bucket>.s3.us-east-1.amazonaws.com/index.html"
export STRIPE_WEBHOOK_SECRET="whsec_..."
python tests/e2e/run_e2e.py --mode live --target cloud --stripe-mode live_cloud --with-browser --tier all --report docs/evidencia-e2e-final.json
```
