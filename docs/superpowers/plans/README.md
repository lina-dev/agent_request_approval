# Reimbursement Platform — Phased Implementation Roadmap

Source spec: [`../specs/2026-06-28-reimbursement-multiagent-design.md`](../specs/2026-06-28-reimbursement-multiagent-design.md)

Each phase below produces working, independently testable software and has its own
plan doc. Build in order; each phase depends only on the ones before it.

## Phase dependency graph

```
P0 Foundation ──► P1 Inference ──► P3 Extraction ──┐
      │                │                            ├─► P6 Adjudication ──► P7 Writeback/HITL ──► P8 Safety+Eval
      │                ├──────────► P4 Policy/RAG ──┤
      └──► P2 Platform API + Orchestrator ──────────┤
                                  P5 Validation/Fraud┘
```

## Phases

| # | Plan doc | Goal | Key deliverable | Depends on |
|---|---|---|---|---|
| **0** | [phase-0-foundation.md](2026-06-28-phase-0-foundation.md) | Repo, IaC skeleton, CI/CD, local dev | `terraform plan` green; CI pipeline runs; `make dev` boots stack | — |
| **1** | [phase-1-inference-layer.md](2026-06-28-phase-1-inference-layer.md) | vLLM pools + LiteLLM gateway on ECS-EC2-GPU | One OpenAI-compatible endpoint routes to VLM/70B/embeddings | P0 |
| **2** | [phase-2-platform-api-orchestrator.md](2026-06-28-phase-2-platform-api-orchestrator.md) | `POST /decisions` (Go) + SQS + LangGraph state machine skeleton | A case flows through stub nodes end-to-end to a (stub) decision | P0 |
| **3** | [phase-3-extraction-agent.md](2026-06-28-phase-3-extraction-agent.md) | VLM extraction worker: receipt image → structured JSON | EXTRACT node returns validated fields + confidence | P1, P2 |
| **4** | [phase-4-policy-rag.md](2026-06-28-phase-4-policy-rag.md) | FAISS + rank_bm25 hybrid retrieval with citations | POLICY_RETRIEVE node returns cited clauses for a query | P1, P2 |
| **5** | [phase-5-validation-fraud.md](2026-06-28-phase-5-validation-fraud.md) | Go deterministic checks (proof completeness, dup, math, FX, tamper) | VALIDATE node returns flags incl. `missing_receipt` | P2 |
| **6** | [phase-6-adjudication-guardrails.md](2026-06-28-phase-6-adjudication-guardrails.md) | Adjudication + threshold policy + output guardrails | ADJUDICATE routes APPROVE/DENY/ESCALATE w/ cited rationale | P3, P4, P5 |
| **7** | [phase-7-writeback-hitl-audit.md](2026-06-28-phase-7-writeback-hitl-audit.md) | Expense-tool adapter, HITL escalation, immutable audit | Decision written back; escalations queued; audit record sealed | P6 |
| **8** | [phase-8-safety-eval-observability.md](2026-06-28-phase-8-safety-eval-observability.md) | PII redaction, injection guards, Langfuse traces, CI-gated eval | Eval gate blocks regressions; traces + PII redaction live | P6, P7 |

## Global tech stack (applies to all phases)

- **Go 1.22+** — API, orchestrator-adjacent plumbing, deterministic validation/fraud, S3/intake, writeback, audit
- **Python 3.12+** — LangGraph orchestration, LLM/ML nodes (extraction, RAG, adjudication), Presidio, eval
- **LangGraph** — supervisor state machine (Python), Postgres checkpointer
- **vLLM** — model serving (Qwen2.5-VL, Llama-3.3-70B/Qwen2.5-72B, bge-m3/e5 embeddings)
- **LiteLLM** — model gateway
- **FAISS** + **rank_bm25** — policy retrieval (no separate vector DB)
- **AWS** — ECS (Fargate + EC2-GPU), RDS Postgres, S3, SQS, SNS, ECR, Secrets Manager
- **Terraform** + **GitHub Actions (OIDC)** + **ArgoCD** — IaC and CD
- **Langfuse** — tracing/observability

## Definition of done per phase

Every phase plan ends with: all tests green, lint clean, committed, and the phase's
"acceptance check" (a single command in the plan) passing.
