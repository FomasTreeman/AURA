# DEVOPS_AUTODEPLOY — AURA
A pragmatic DevOps specification to make AURA bullet‑proof for automatic testing, deployment, security, performance, and developer experience. This document is intended as a clear implementation blueprint for infra, CI/CD, testing, monitoring, and housekeeping.

Important note: this spec is explicitly written to support and maintain parity between two deployment models — cloud-native deployments (Kubernetes / managed infra) and LAN‑first / on‑prem deployments (hosted on office devices, Tailscale/headscale, or air‑gapped installs). The project will use a single source codebase and a single container image, with runtime configuration and deployment manifests enabling the same artifact to be deployed into cloud or LAN/air‑gapped environments. CI will build and sign both registry-push artifacts and offline/signed bundles to support automated cloud rollout and secure LAN installs respectively.

Contents
- Goals & assumptions
- High-level architecture
- Deployment targets (lightweight → production; cloud & LAN-first)
- Infrastructure as Code (IaC)
- CI / CD pipeline (GitHub Actions recommended) — builds for both registry and offline bundles
- Build / Release / Rollout strategy (cloud canary + offline signed bundles for LAN)
- Testing matrix (unit / integration / e2e) covering both cloud and LAN scenarios
- Security & compliance controls
- Observability & SLOs / alerts
- DX / developer tooling (single-image workflow, host-network compose examples)
- Checklist & runbook items

------------------------------------------------------------------------
Goals & assumptions
- Goal: fully automated test → build → deploy pipeline with gated PRs, dependency/security scanning, robust staging and safe production rollouts (canary/blue‑green), observability, and policy enforcement.
- The service is lightweight by design (RAG + Ollama + ChromaDB). It can run on a single machine for dev and proof-of-concept but needs resilient infra for production (multiple nodes, backing stores, secrets management).
- Assumptions:
  - LLM server: Ollama (local model server) — may require local GPU/CPU resources.
  - Vector DB: Chroma (deployed as a service or container).
  - Session/coordination store: Redis (for rate limiting, sessions, locks).
  - Storage: S3-compatible object store for backups & artifacts.
  - Cloud provider: recommendations cover AWS, GCP, Azure, and DigitalOcean.

------------------------------------------------------------------------
High-level architecture
- Components:
  - API service: `backend` (FastAPI). SSE endpoints for streaming responses.
  - LLM service: Ollama (local or dedicated instance; may be co-located or on separate GPU host).
  - Vector DB: Chroma (docker or managed)
  - Redis: session & rate-limit store
  - Optional DB for metadata (Postgres) if you want persistent ingestion metadata/audit logs
  - Reverse proxy / TLS termination: ALB / NGINX / Traefik
  - Service mesh (optional): Istio/mTLS for peer auth in federated mode
  - Observability: Prometheus + Grafana, centralized logs (CloudWatch/ELK)
- Networking:
  - VPC with private subnets for backend/Chroma/Ollama; public LB in public subnet as entrypoint
  - Security groups defaults: deny all inbound except LB; no open DB ports to internet
- Single-node dev: `docker-compose` that runs `backend`, `chroma`, `redis`, and a mocked/stubbed `ollama` (or a small CPU model)

------------------------------------------------------------------------
Deployment targets and sizing (where to deploy)
- Tiny / Dev:
  - Single VM or local Docker Compose on developer machine
  - Provider examples: DigitalOcean droplet, local laptop, local VM
  - Minimal: 4 vCPU, 8–16 GB RAM, local SSD (for Chroma)
- Small production (budget-conscious):
  - Single-az managed VM cluster (or small k8s cluster): 2–3 nodes (m/large CPU)
  - Managed services: Redis (Elasticache), RDS Postgres (optional), S3 for backups
  - Ollama may be run on a dedicated host (m128gb) if running large models; CPU-only works with smaller models but slower
- Cloud-native scalable:
  - Kubernetes cluster (EKS, GKE, AKS), or ECS Fargate for container orchestration
  - Autoscale controllers:
    - HorizontalPodAutoscaler for backend (scale by CPU/requests)
    - Node pools for Ollama (GPU nodes if required)
  - Use Network Load Balancer for long-lived SSE connections (HTTP/1.1). Ensure LB supports connection idle timeout > SSE lifetime.
- Serverless candidate:
  - Cloud Run / App Engine or Lambda for stateless endpoints is possible, but SSE and long-lived streaming are harder to support; binary streaming and long-lived connections favor K8s or container services.

Decision hints:
- If you require long-lived SSE and local Ollama with GPU, target K8s/ECS on VM/GPU nodes.
- For minimal public exposure and testing, a single droplet + docker-compose is fine behind a TLS reverse proxy and firewall.

------------------------------------------------------------------------
Infrastructure as Code (IaC)
- Use Terraform for multi-cloud reproducibility.
- Terraform modules / resources (sketch):
  - Networking: VPC, private subnets, NAT, route tables
  - Compute: EKS / ECS / VM(s) + node pools (GPU pool optional)
  - Storage: S3 buckets, KMS keys for encryption
  - Secrets: AWS Secrets Manager / Parameter Store (or HashiCorp Vault)
  - Databases: RDS Postgres (optional), Elasticache Redis
  - Load Balancer: ALB/NLB with TLS cert (ACM or managed cert)
  - Observability: CloudWatch log groups / Prometheus node exporters
- IaC workflow:
  - `terraform fmt` + `terraform validate` in CI
  - PRs open a plan preview (use `tflint`, `checkov` or policy-as-code)
  - Apply only via protected merge to `main` with CI/CD runner service account

------------------------------------------------------------------------
CI / CD Pipeline (GitHub Actions recommended)
- Overview pipeline:
  - On PR:
    - 1) Linting: `black` (format check), `isort`, `ruff`/`flake8`, `mypy` (optional)
    - 2) Pre-commit hooks (via `pre-commit`): enforce formatting locally & in CI
    - 3) Unit tests: `pytest` with coverage threshold (e.g., > 80%)
    - 4) Security scans:
      - `detect-secrets` (fail on high-confidence)
      - `pip-audit` & `safety`
      - `bandit` for SAST
    - 5) Dependency automation: Dependabot (external) creates PRs for upgrades
    - 6) Build docker image and run integration tests against a mocked Ollama (or test container) — **do not** call production Ollama from CI
    - 7) Container image push to registry on merge to `main` (ECR/GCR/DockerHub)
    - 8) Terraform plan/apply (apply gated; typically target staging first)
  - On merge to `main`:
    - Deploy to `staging` automatically (blue/green or rolling)
    - Run smoke integration tests against staging
    - If smoke tests pass and manual gating enabled, deploy to production (or if fully automated, continue with canary policies)
- GitHub Actions examples (job names):
  - `lint`, `unit-tests`, `security-scan`, `build-and-smoke`, `push-image`, `terraform-plan`, `deploy-staging`, `integration-tests`, `deploy-prod`
- Workflow details:
  - Use reusable workflow templates for build/test/deploy stages
  - Use secret scanning results and failing PR if secrets are detected
  - Use artifact caching for pip and docker layers to speed builds

------------------------------------------------------------------------
Build / Release / Rollout strategy
- Build:
  - Use multi-stage Dockerfile to produce a minimal runtime image (slim Python base)
  - Tag images with `sha` and semantic tags
  - Scan produced images for vulnerabilities in CI (e.g., trivy)
- Release:
  - Deploy to `staging` on every `main` merge
  - Run integration smoke tests (mock LLM)
  - Promote to `production` via:
    - Canary (recommended): route 5% traffic → 50% → 100% with automated monitoring checks (error rate, latency)
    - Blue-green: deploy new revision, run health checks, swap traffic
- Rollback:
  - Automatic rollback if errors exceed threshold (e.g., increased 5xx or SLO breach)
  - Manual rollback via image tag revert
- Versioning:
  - Use semantic versioning in `CHANGELOG.md` and automated release notes via commit messages (conventional commits)

------------------------------------------------------------------------
Testing matrix & environment strategy
- Tests to run in CI:
  - Unit tests: pure code paths with mocks for network/LLM
  - Integration tests (fast):
    - Run service with a stubbed Ollama that returns deterministic token streams (containerized)
    - Run Chroma in ephemeral container with a small in-memory DB for retrieval tests
  - Contract tests: ensure API shape and SSE formatting remain stable
  - Security tests:
    - Prompt injection regression test (mock LLM contains malicious behavior)
    - Data-leak regression tests (ingest known sentinel tokens and assert not returned)
  - Performance tests (periodic/nightly or pre-prod):
    - Load test streaming endpoints (k6 or locust)
    - Spike test for SSE connection limits
- Test environments:
  - `local` (developer): `docker-compose` for rapid iteration
  - `ci`: ephemeral containers, mocked LLM
  - `staging`: production-like (smaller scale), real Chroma+Ollama instances
  - `production`: scaled deployment with full monitoring

------------------------------------------------------------------------
Security & compliance (operational)
- Authentication:
  - All endpoints must require auth (API keys / JWT / OAuth). Use short-lived tokens for user-level auth.
  - SSE connections require Authorization header and enforce per-API-key quotas.
- Secrets:
  - Do not commit secrets. Use `secrets manager` per cloud or Vault.
  - Rotate keys regularly and support key revocation.
- Network:
  - TLS termination at LB (ACME/managed certificate). All internal services in private subnets.
  - WAF rules for common injection vectors.
- Runtime protection:
  - Rate limiting (per-key and per-IP), connection caps, max tokens per request, and CPU/memory resource quotas.
- Federated trust:
  - Peers must be mutually authenticated (mTLS or signed tokens). Reject untrusted peers; log and quarantine suspicious responses.
- Logging and privacy:
  - Redact sensitive fields (PII) before logging.
  - Logs must be stored in an access-controlled store and retained per policy.
- CI security:
  - Run `detect-secrets` on PRs, `pip-audit` in CI, dependabot enabled.
  - Fail PR on critical CVEs in dependencies.
- Incident handling:
  - Automated rotation of keys on suspected compromise, revoke active sessions, and full audit trail for ingestion & admin actions.

------------------------------------------------------------------------
Observability, metrics, and SLOs
- Metrics (expose via Prometheus):
  - Request rate, latencies, errors (4xx/5xx)
  - SSE connections: total, active, per-key concurrent
  - LLM token usage: tokens generated per query, tokens billed per key
  - Retrival metrics: retrieval time, chunks returned
  - Carbon / green metrics (already present in code)
- Logging:
  - Structured JSON logs with correlation IDs for each query
  - Masked user content; include sparse metadata for debugging (hash of question)
- Tracing:
  - Add OpenTelemetry tracing for request → retrieval → LLM stream steps
- Alerts:
  - Error rate > threshold, SLO breaches, sudden spike in tokens usage, many rejected auth attempts
- Dashboards:
  - Grafana dashboards for traffic, SSE connections, LLM costs, latency, and error rates

Suggested SLOs:
- Availability: 99.9% for API endpoints (excluding scheduled maintenance)
- Latency: 95th percentile response time < N ms for typical queries (tune after baseline)
- Error rate: < 0.5% 5xx over rolling 10m window

------------------------------------------------------------------------
Developer Experience (DX)
- Local dev:
  - `docker-compose.yml` with services: `backend`, `chroma`, `redis`, `mock-ollama` and scripts in `Makefile`:
    - `make dev` → run backend in hot-reload mode
    - `make test` → run pytest
  - `.env.example` and `config` loader with clear env var names
- Pre-commit & lint:
  - `pre-commit` hooks: `black`, `isort`, `ruff`/`flake8`, `mypy`
  - Enforce in CI; provide git hook install instructions
- Code quality:
  - `pytest` with coverage; enforce minimal coverage gate
  - `ruff`/`flake8` for lint; `mypy` for typing if adopted
- Dependency management:
  - `requirements.txt` with pinned deps or `poetry` for more reproducible envs
  - Dependabot configured for both direct and transitive upgrades; maintain an owner/review process
- Onboarding:
  - `README.dev` with 5-10 step onboarding for new devs to run locally
  - `docs/ops.md`: how to deploy, rotate secrets, and triage errors
- Secrets in local dev:
  - Use `.env` for local secrets; ensure `.env` is in `.gitignore`
- Convenience:
  - CLI tasks: `scripts/seed_db.py`, `scripts/ingest_sample.py`, `scripts/mock_ollama.py` for testing streaming behavior

------------------------------------------------------------------------
Dependabot, linting, and "all bells and whistles"
- Dependabot:
  - Enable for `pip` and GitHub Actions, configured to open PRs weekly
  - Auto-merge low-risk bumps after successful CI tests (configurable)
- Lint/security tools:
  - `pre-commit` with `black`, `isort`, `ruff`, `trailing-whitespace`, `end-of-file-fixer`
  - CI steps: `bandit`, `pip-audit`, `safety`, `mypy` (optional), `mend`, or other SCA tools
- Container scanning:
  - `trivy` or `clair` run in CI on built images
- Secrets scanning:
  - `detect-secrets` pre-commit + CI detection
- Infrastructure policy:
  - Integrate `checkov` or `tfsec` into IaC pipeline; fail on critical findings
- Performance gating:
  - Nightly job: run a small load test and track regressions; fail PRs that degrade baseline performance metrics (optional)

------------------------------------------------------------------------
Checklist & runbook (practical steps)
- Before public exposure:
  - [ ] Auth required on all endpoints
  - [ ] Rate limits & SSE connection caps in place
  - [ ] Secrets manager & no secrets in repo
  - [ ] Dependabot, pip-audit, detect-secrets configured in CI
  - [ ] Centralized logging & redaction policy
  - [ ] Backups enabled for Chroma & Redis; encryption at rest
  - [ ] Basic Prometheus + Grafana dashboards; alerting rules configured
- On each PR:
  - `pre-commit` enforced, unit tests pass, linting passes, security scans pass
- On deploy:
  - Image scanned, smoke tests passed on staging, canary monitor checks passed before full rollout

------------------------------------------------------------------------
Appendix — recommended GitHub Actions job layout (high level)
- `lint` — run `black --check`, `ruff`, `isort --check`
- `unit-tests` — `pytest -q --maxfail=1 --cov=backend`
- `security-scan` — run `pip-audit`, `bandit`
- `build-image` — docker build, trivy scan
- `integration` — start containers (chroma+mock-ollama), run smoke tests
- `terraform-plan` — run tf plan only for PR (comment plan)
- `deploy-staging` — push image & apply k8s helm/Terraform to staging
- `integration-staging-tests` — end-to-end tests against staging
- `deploy-prod` — canary rollout (requires manual approval or configured policy)

------------------------------------------------------------------------
Closing recommendations
1. Start small and iterate:
   - Implement auth, secrets management, rate limiting, logging redaction, and basic CI scans first.
   - Add infra automation (Terraform) and a staging environment second.
2. Invest in test harnesses for mocking the LLM:
   - CI must never call production Ollama; use a mock server that emits deterministic SSE/NDJSON responses.
3. Make security and dependency scanning non-optional:
   - Enforce via branch protection and failing CI on critical issues.
4. Monitor cost vectors carefully:
   - Track token usage per API key and set hard quotas to avoid runaway bills.
5. Document operational runbooks:
   - Keep quick steps to rotate credentials, revoke API keys, and rollback deployments.

If you want, next steps I can produce:
- A concrete `github/workflows/ci.yml` template (GitHub Actions) tuned for this repo (lint, test, build, scan).
- A `docker-compose.dev.yml` for local dev including `mock-ollama`, `chroma`, and `redis`.
- A Terraform module skeleton for AWS EKS + Redis + S3 + ALB.
Pick one and I'll produce the artifact.