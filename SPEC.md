# k8s-ops-agent — SPEC

> AIOps agent that monitors a Kubernetes cluster, analyses incidents with AI, and optionally executes fixes with human approval.

---

## Problem Statement

Kubernetes clusters produce a constant stream of events. When a pod crashes, gets OOM-killed, or enters a CrashLoopBackOff, someone on call must manually correlate logs, events, and resource usage to find the root cause. This takes time and requires deep cluster knowledge.

`k8s-ops-agent` automates this. It monitors the cluster, filters signal from noise, and uses an AI agent to diagnose incidents — delivering a structured analysis with probable cause, evidence, and a suggested fix command.

---

## Architecture

```
K8s Cluster
    │ Warning events (OOMKilled, CrashLoopBackOff, etc.)
    ▼
Collector (background thread)
    │ filters + deduplicates
    ▼
PostgreSQL — stores raw incident
    │
    ▼
ReAct Agent (LangChain + Claude)
    │ iterates: Thought → K8s Tool → Observation
    ├── get_pod_logs
    ├── describe_pod
    ├── list_events
    └── get_node_status
    │
    ▼
Analysis stored in DB
    │
    ├── Assisted mode  → GET /incidents/{id} returns report
    └── Autonomous mode → POST /incidents/{id}/approve → executes fix
```

---

## Project structure

```
k8s-ops-agent/
├── main.py           # FastAPI app + lifespan (starts collector)
├── collector.py      # K8s event poller — background thread
├── agent.py          # LangChain ReAct agent + analysis parser
├── k8s_tools.py      # Agent tools: logs, describe, events, nodes
├── database.py       # SQLAlchemy engine + session factory
├── models.py         # ORM model (Incident) + Pydantic schemas
├── Dockerfile
├── docker-compose.yml
├── SPEC.md
├── .env.example
└── requirements.txt
```

---

## Stack

```
fastapi + uvicorn       — API layer
langchain               — ReAct agent framework
langchain-anthropic     — Claude provider
kubernetes              — official Python client for K8s
sqlalchemy              — ORM
psycopg2-binary         — PostgreSQL driver
pydantic                — request/response schemas
python-dotenv           — env var loading
```

---

## K8s Tools (read-only)

| Tool | Input | What it does |
|---|---|---|
| `get_pod_logs` | `pod-name/namespace` | Last 50 lines of container logs |
| `describe_pod` | `pod-name/namespace` | Phase, conditions, restart count, state |
| `list_events` | `namespace` | Last 20 Warning events in namespace |
| `get_node_status` | — | CPU + memory capacity/allocatable per node |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/incidents` | List incidents (filter by namespace, status) |
| `GET` | `/incidents/{id}` | Incident details + AI analysis |
| `POST` | `/incidents/{id}/approve` | Approve fix (autonomous mode only) |

---

## Incident lifecycle

```
analyzing → analyzed → fix_pending → fix_applied
```

---

## Modes

| | Assisted (default) | Autonomous |
|---|---|---|
| Analyzes incident | ✓ | ✓ |
| Suggests fix command | ✓ | ✓ |
| Executes fix | ✗ | On POST /approve |
| Config | `AGENT_MODE=assisted` | `AGENT_MODE=autonomous` |

---

## Technical decisions

| Decision | Why |
|---|---|
| `kubernetes` Python client | No dependency on kubectl binary — works in-cluster and locally |
| Collector as background thread | Single container deploy — no separate worker process |
| PostgreSQL | Production-grade storage with queryable history |
| Assisted mode by default | Safety first — autonomous execution is opt-in |
| Deduplication via event resource_version | Prevents re-processing the same event on every poll |

---

## Contract — done when

- [ ] Collector detects OOMKilled and CrashLoopBackOff pods
- [ ] Agent performs at least 2 K8s tool calls before concluding
- [ ] Incident stored in DB with full analysis
- [ ] `GET /incidents/{id}` returns analysis + fix_command
- [ ] Assisted mode works end-to-end
- [ ] `docker compose up` starts app + PostgreSQL without manual config
