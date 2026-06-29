# Phase 0: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the repo structure, Terraform skeleton, CI/CD pipeline, and a local dev stack so every later phase has a place to land and a green pipeline to ship through.

**Architecture:** Mono-repo with a Go module (`/services/go`), a Python package (`/services/py`), and Terraform (`/infra`). GitHub Actions authenticates to AWS via OIDC (no static keys), runs lint/test/scan, and `terraform plan` on PRs. A `docker-compose` provides local Postgres + LocalStack (S3/SQS) for development.

**Tech Stack:** Go 1.22, Python 3.12, Terraform 1.7+, GitHub Actions, Docker Compose, LocalStack, golangci-lint, ruff, trivy, checkov.

## Global Constraints

- Go 1.22+; Python 3.12+.
- No static AWS keys anywhere — GitHub Actions uses OIDC role assumption only.
- All infra in Terraform; no console-created resources.
- Every service containerized; images pushed to ECR.
- Region: `us-east-1` (single region for now).
- Secrets in AWS Secrets Manager, never in repo.

---

## File structure

```
/Makefile                         # dev entrypoints (dev, test, lint, plan)
/docker-compose.yml               # local Postgres + LocalStack
/services/go/go.mod               # Go module root
/services/go/internal/health/     # trivial health package (proves Go build/test)
/services/py/pyproject.toml        # Python package
/services/py/reimb/__init__.py
/services/py/tests/test_smoke.py
/infra/main.tf                     # provider + backend
/infra/variables.tf
/infra/modules/network/            # VPC module
/infra/modules/ecr/                # ECR repos
/.github/workflows/ci.yml          # lint + test + scan + terraform plan
/.github/workflows/oidc-bootstrap.md  # docs for the one-time OIDC role
```

---

### Task 1: Go module + health package

**Files:**
- Create: `services/go/go.mod`
- Create: `services/go/internal/health/health.go`
- Test: `services/go/internal/health/health_test.go`

**Interfaces:**
- Produces: `health.Status() string` returning `"ok"`.

- [ ] **Step 1: Write the failing test**

```go
// services/go/internal/health/health_test.go
package health

import "testing"

func TestStatusReturnsOK(t *testing.T) {
	if got := Status(); got != "ok" {
		t.Fatalf("Status() = %q, want %q", got, "ok")
	}
}
```

- [ ] **Step 2: Init module and run test (expect compile failure)**

Run:
```bash
cd services/go && go mod init github.com/acme/reimb-go && go test ./internal/health/...
```
Expected: FAIL — `undefined: Status`.

- [ ] **Step 3: Implement minimal code**

```go
// services/go/internal/health/health.go
package health

// Status reports service liveness.
func Status() string { return "ok" }
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/go && go test ./internal/health/...`
Expected: PASS (`ok ... health`).

- [ ] **Step 5: Commit**

```bash
git add services/go
git commit -m "chore(go): init module with health package"
```

---

### Task 2: Python package + smoke test

**Files:**
- Create: `services/py/pyproject.toml`
- Create: `services/py/reimb/__init__.py`
- Test: `services/py/tests/test_smoke.py`

**Interfaces:**
- Produces: `reimb.__version__` string.

- [ ] **Step 1: Write the failing test**

```python
# services/py/tests/test_smoke.py
import reimb

def test_version_present():
    assert isinstance(reimb.__version__, str)
    assert reimb.__version__
```

- [ ] **Step 2: Create pyproject and run test (expect failure)**

```toml
# services/py/pyproject.toml
[project]
name = "reimb"
version = "0.1.0"
requires-python = ">=3.12"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
pythonpath = ["."]
```

Run: `cd services/py && python -m pytest -q`
Expected: FAIL — `AttributeError: module 'reimb' has no attribute '__version__'`.

- [ ] **Step 3: Implement minimal code**

```python
# services/py/reimb/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && python -m pytest -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add services/py
git commit -m "chore(py): init reimb package with smoke test"
```

---

### Task 3: Terraform skeleton (network + ECR) with validate

**Files:**
- Create: `infra/main.tf`, `infra/variables.tf`
- Create: `infra/modules/network/main.tf`, `infra/modules/network/variables.tf`, `infra/modules/network/outputs.tf`
- Create: `infra/modules/ecr/main.tf`, `infra/modules/ecr/variables.tf`
- Test: `infra/main_test.go` (Terratest-style validate) — optional; primary gate is `terraform validate`.

**Interfaces:**
- Produces: VPC with public+private subnets; ECR repos `reimb-go`, `reimb-py`, `vllm`, `litellm`.

- [ ] **Step 1: Write provider + backend**

```hcl
# infra/main.tf
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {} # configured via -backend-config at init
}

provider "aws" {
  region = var.region
}

module "network" {
  source = "./modules/network"
  name   = "reimb"
  cidr   = "10.20.0.0/16"
}

module "ecr" {
  source = "./modules/ecr"
  repos  = ["reimb-go", "reimb-py", "vllm", "litellm"]
}
```

```hcl
# infra/variables.tf
variable "region" {
  type    = string
  default = "us-east-1"
}
```

- [ ] **Step 2: Write the network module**

```hcl
# infra/modules/network/variables.tf
variable "name" { type = string }
variable "cidr" { type = string }
```

```hcl
# infra/modules/network/main.tf
resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.cidr, 4, count.index)
  availability_zone = data.aws_availability_zones.azs.names[count.index]
  tags              = { Name = "${var.name}-private-${count.index}" }
}

data "aws_availability_zones" "azs" { state = "available" }
```

```hcl
# infra/modules/network/outputs.tf
output "vpc_id" { value = aws_vpc.this.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
```

- [ ] **Step 3: Write the ECR module**

```hcl
# infra/modules/ecr/variables.tf
variable "repos" { type = list(string) }
```

```hcl
# infra/modules/ecr/main.tf
resource "aws_ecr_repository" "this" {
  for_each             = toset(var.repos)
  name                 = each.value
  image_scanning_configuration { scan_on_push = true }
}
```

- [ ] **Step 4: Validate**

Run: `cd infra && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra
git commit -m "infra: terraform skeleton with network and ECR modules"
```

---

### Task 4: Local dev stack (compose) + Makefile

**Files:**
- Create: `docker-compose.yml`
- Create: `Makefile`

**Interfaces:**
- Produces: `make dev` brings up Postgres (5432) + LocalStack (4566); `make test` runs Go+Py tests.

- [ ] **Step 1: Write compose**

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: dev
      POSTGRES_DB: reimb
    ports: ["5432:5432"]
  localstack:
    image: localstack/localstack:3
    environment:
      SERVICES: s3,sqs,sns
    ports: ["4566:4566"]
```

- [ ] **Step 2: Write Makefile**

```makefile
# Makefile
.PHONY: dev down test lint plan
dev:
	docker compose up -d
down:
	docker compose down
test:
	cd services/go && go test ./...
	cd services/py && python -m pytest -q
lint:
	cd services/go && go vet ./...
	cd services/py && ruff check .
plan:
	cd infra && terraform init -backend=false && terraform validate
```

- [ ] **Step 3: Verify dev stack boots**

Run: `make dev && docker compose ps`
Expected: both `postgres` and `localstack` show `running`/healthy. Then `make down`.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml Makefile
git commit -m "chore: local dev stack and Makefile targets"
```

---

### Task 5: CI pipeline (OIDC, lint, test, scan, terraform plan)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/oidc-bootstrap.md`

**Interfaces:**
- Produces: PR pipeline running Go+Py tests, ruff/go vet, trivy + checkov, `terraform validate`.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/ci.yml
name: ci
on:
  pull_request:
permissions:
  id-token: write   # OIDC
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: "1.22" }
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: cd services/go && go test ./... && go vet ./...
      - run: cd services/py && pip install ruff pytest && ruff check . && python -m pytest -q
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@0.24.0
        with: { scan-type: fs, scan-ref: . }
      - uses: bridgecrewio/checkov-action@v12
        with: { directory: infra }
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - run: cd infra && terraform init -backend=false && terraform validate
```

- [ ] **Step 2: Document the one-time OIDC role**

```markdown
# .github/workflows/oidc-bootstrap.md
Create an IAM OIDC provider for token.actions.githubusercontent.com and a role
`gha-reimb-ci` with a trust policy scoped to this repo's `ref` and `environment`.
Grant least-privilege: ECR push, Terraform plan read. No long-lived keys.
```

- [ ] **Step 3: Validate workflow locally**

Run: `cd services/go && go test ./... && cd ../py && python -m pytest -q`
Expected: both green (mirrors what CI runs).

- [ ] **Step 4: Commit**

```bash
git add .github
git commit -m "ci: OIDC pipeline with test, scan, and terraform validate"
```

---

## Acceptance check

```bash
make test && make plan
```
Expected: Go + Python tests pass and `terraform validate` reports success.

## Self-review notes

- Covers spec §10 (CI/CD foundations, OIDC, Terraform, scans) and the repo scaffolding
  implied by §2/§12. vLLM/RDS/SQS resources are intentionally deferred to the phases that
  consume them (P1, P2) to keep each phase independently testable.
