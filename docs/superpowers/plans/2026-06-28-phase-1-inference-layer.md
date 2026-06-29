# Phase 1: Inference Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve three model pools (VLM, 70B reasoning, embeddings) on vLLM over ECS-EC2-GPU, fronted by a single LiteLLM gateway that agents call by logical model name.

**Architecture:** Terraform provisions an ECS cluster with an EC2-GPU capacity provider (g5/g6) and a Fargate service for LiteLLM. vLLM runs one task per model pool, each exposing an OpenAI-compatible endpoint. LiteLLM maps logical names (`extractor`, `adjudicator`, `embedder`) to the pools and enforces per-agent virtual keys + budgets. A Python client wrapper is the only way app code talks to models.

**Tech Stack:** vLLM, LiteLLM, ECS (EC2-GPU capacity provider + Fargate), Terraform, Python httpx.

## Global Constraints

- Agents NEVER call vLLM directly — only via LiteLLM gateway.
- GPU nodes scale toward zero on idle (SQS depth driver added in P2).
- 70B served quantized (AWQ or FP8), tensor-parallel as needed.
- Prefix caching enabled (shared policy system prompt).
- Logical model names are stable contracts: `extractor`, `adjudicator`, `embedder`.

---

## File structure

```
/infra/modules/ecs_gpu/            # ECS cluster + EC2-GPU capacity provider
/infra/modules/vllm_service/       # reusable vLLM ECS service (per pool)
/infra/litellm/config.yaml         # gateway model map + routing
/services/py/reimb/llm/gateway.py  # LiteLLM client wrapper (the only model entrypoint)
/services/py/tests/llm/test_gateway.py
```

---

### Task 1: ECS GPU cluster + capacity provider (Terraform)

**Files:**
- Create: `infra/modules/ecs_gpu/main.tf`, `variables.tf`, `outputs.tf`
- Modify: `infra/main.tf` (wire module)

**Interfaces:**
- Produces: outputs `cluster_arn`, `gpu_capacity_provider`.

- [ ] **Step 1: Write the module**

```hcl
# infra/modules/ecs_gpu/main.tf
resource "aws_ecs_cluster" "this" { name = var.name }

resource "aws_autoscaling_group" "gpu" {
  name                = "${var.name}-gpu"
  min_size            = 0          # scale-to-zero
  max_size            = var.max_gpu_nodes
  desired_capacity    = 0
  vpc_zone_identifier = var.subnet_ids
  launch_template {
    id      = aws_launch_template.gpu.id
    version = "$Latest"
  }
  tag { key = "AmazonECSManaged" value = "" propagate_at_launch = true }
}

resource "aws_launch_template" "gpu" {
  name_prefix   = "${var.name}-gpu-"
  instance_type = var.gpu_instance_type # e.g. g5.2xlarge
  image_id      = var.ecs_gpu_ami       # ECS GPU-optimized AMI
}

resource "aws_ecs_capacity_provider" "gpu" {
  name = "${var.name}-gpu-cp"
  auto_scaling_group_provider {
    auto_scaling_group_arn = aws_autoscaling_group.gpu.arn
    managed_scaling { status = "ENABLED" target_capacity = 100 }
  }
}
```

```hcl
# infra/modules/ecs_gpu/outputs.tf
output "cluster_arn" { value = aws_ecs_cluster.this.arn }
output "gpu_capacity_provider" { value = aws_ecs_capacity_provider.gpu.name }
```

- [ ] **Step 2: Validate**

Run: `cd infra && terraform init -backend=false && terraform validate`
Expected: `Success! The configuration is valid.`

- [ ] **Step 3: Commit**

```bash
git add infra/modules/ecs_gpu infra/main.tf
git commit -m "infra: ECS GPU cluster with scale-to-zero capacity provider"
```

---

### Task 2: vLLM service module (parameterized per pool)

**Files:**
- Create: `infra/modules/vllm_service/main.tf`, `variables.tf`
- Modify: `infra/main.tf` (instantiate three pools)

**Interfaces:**
- Consumes: `cluster_arn`, `gpu_capacity_provider` from Task 1.
- Produces: an internal ALB/endpoint per pool.

- [ ] **Step 1: Write the module (task def + service)**

```hcl
# infra/modules/vllm_service/variables.tf
variable "pool_name" { type = string }   # extractor | adjudicator | embedder
variable "model_id"  { type = string }   # HF model id
variable "extra_args" { type = list(string) default = [] }
variable "cluster_arn" { type = string }
variable "capacity_provider" { type = string }
```

```hcl
# infra/modules/vllm_service/main.tf
resource "aws_ecs_task_definition" "vllm" {
  family                   = "vllm-${var.pool_name}"
  requires_compatibilities = ["EC2"]
  container_definitions = jsonencode([{
    name  = "vllm"
    image = "${var.ecr_vllm}:latest"
    command = concat([
      "--model", var.model_id,
      "--enable-prefix-caching"
    ], var.extra_args)
    resourceRequirements = [{ type = "GPU", value = "1" }]
    portMappings = [{ containerPort = 8000 }]
  }])
}

resource "aws_ecs_service" "vllm" {
  name            = "vllm-${var.pool_name}"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.vllm.arn
  desired_count   = 1
  capacity_provider_strategy {
    capacity_provider = var.capacity_provider
    weight            = 1
  }
}
```

- [ ] **Step 2: Instantiate three pools in main.tf**

```hcl
module "vllm_extractor" {
  source = "./modules/vllm_service"
  pool_name = "extractor"
  model_id  = "Qwen/Qwen2.5-VL-7B-Instruct"
  cluster_arn = module.ecs_gpu.cluster_arn
  capacity_provider = module.ecs_gpu.gpu_capacity_provider
}
module "vllm_adjudicator" {
  source = "./modules/vllm_service"
  pool_name = "adjudicator"
  model_id  = "meta-llama/Llama-3.3-70B-Instruct"
  extra_args = ["--quantization", "awq", "--tensor-parallel-size", "2"]
  cluster_arn = module.ecs_gpu.cluster_arn
  capacity_provider = module.ecs_gpu.gpu_capacity_provider
}
module "vllm_embedder" {
  source = "./modules/vllm_service"
  pool_name = "embedder"
  model_id  = "BAAI/bge-m3"
  cluster_arn = module.ecs_gpu.cluster_arn
  capacity_provider = module.ecs_gpu.gpu_capacity_provider
}
```

- [ ] **Step 3: Validate & commit**

Run: `cd infra && terraform validate`
Expected: success.
```bash
git add infra/modules/vllm_service infra/main.tf
git commit -m "infra: three vLLM pools (extractor/adjudicator/embedder)"
```

---

### Task 3: LiteLLM gateway config + Fargate service

**Files:**
- Create: `infra/litellm/config.yaml`
- Create: `infra/modules/litellm/main.tf`

**Interfaces:**
- Produces: gateway base URL; logical names `extractor`, `adjudicator`, `embedder`.

- [ ] **Step 1: Write the gateway model map**

```yaml
# infra/litellm/config.yaml
model_list:
  - model_name: extractor
    litellm_params:
      model: openai/Qwen/Qwen2.5-VL-7B-Instruct
      api_base: http://vllm-extractor.internal:8000/v1
  - model_name: adjudicator
    litellm_params:
      model: openai/meta-llama/Llama-3.3-70B-Instruct
      api_base: http://vllm-adjudicator.internal:8000/v1
  - model_name: embedder
    litellm_params:
      model: openai/BAAI/bge-m3
      api_base: http://vllm-embedder.internal:8000/v1
litellm_settings:
  drop_params: true
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
```

- [ ] **Step 2: Write the Fargate service (CPU)**

```hcl
# infra/modules/litellm/main.tf
resource "aws_ecs_task_definition" "litellm" {
  family                   = "litellm"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  network_mode             = "awsvpc"
  container_definitions = jsonencode([{
    name  = "litellm"
    image = "${var.ecr_litellm}:latest"
    command = ["--config", "/app/config.yaml", "--port", "4000"]
    portMappings = [{ containerPort = 4000 }]
  }])
}
```

- [ ] **Step 3: Validate & commit**

Run: `cd infra && terraform validate`
```bash
git add infra/litellm infra/modules/litellm
git commit -m "infra: LiteLLM gateway on Fargate with model map"
```

---

### Task 4: Python gateway client wrapper (the only model entrypoint)

**Files:**
- Create: `services/py/reimb/llm/gateway.py`
- Test: `services/py/tests/llm/test_gateway.py`

**Interfaces:**
- Produces: `Gateway(base_url, api_key).chat(model: str, messages: list[dict], **kw) -> dict`
  and `Gateway.embed(texts: list[str]) -> list[list[float]]`.

- [ ] **Step 1: Write the failing test (mock the HTTP layer)**

```python
# services/py/tests/llm/test_gateway.py
import respx, httpx
from reimb.llm.gateway import Gateway

@respx.mock
def test_chat_routes_to_logical_model():
    route = respx.post("http://gw/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hi"}}]
        })
    )
    gw = Gateway(base_url="http://gw", api_key="sk-test")
    out = gw.chat("adjudicator", [{"role": "user", "content": "hello"}])
    assert out["choices"][0]["message"]["content"] == "hi"
    sent = route.calls.last.request
    assert b'"model":"adjudicator"' in sent.content.replace(b" ", b"")
```

- [ ] **Step 2: Run test (expect failure)**

Run: `cd services/py && python -m pytest tests/llm/test_gateway.py -q`
Expected: FAIL — `ModuleNotFoundError: reimb.llm.gateway`.

- [ ] **Step 3: Implement the wrapper**

```python
# services/py/reimb/llm/gateway.py
import httpx

class Gateway:
    """Single entrypoint to all models via the LiteLLM gateway."""
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def chat(self, model: str, messages: list[dict], **kw) -> dict:
        resp = self._client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": messages, **kw},
        )
        resp.raise_for_status()
        return resp.json()

    def embed(self, texts: list[str], model: str = "embedder") -> list[list[float]]:
        resp = self._client.post("/v1/embeddings", json={"model": model, "input": texts})
        resp.raise_for_status()
        return [d["embedding"] for d in resp.json()["data"]]
```

- [ ] **Step 4: Run test to verify pass**

Run: `cd services/py && pip install httpx respx && python -m pytest tests/llm/test_gateway.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/py/reimb/llm services/py/tests/llm
git commit -m "feat(llm): LiteLLM gateway client wrapper"
```

---

## Acceptance check

```bash
cd infra && terraform validate
cd ../services/py && python -m pytest tests/llm -q
```
Expected: Terraform valid; gateway wrapper tests pass. (Live GPU smoke test runs post-`apply` in a staging deploy.)

## Self-review notes

- Covers spec §5 (vLLM pools, LiteLLM gateway, prefix caching, quantization, scale-to-zero).
- Live model smoke (real tokens) is a staging-deploy step, not a unit test — noted intentionally.
