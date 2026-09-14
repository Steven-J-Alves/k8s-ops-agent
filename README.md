# k8s-ops-agent

> AIOps agent that monitors a Kubernetes cluster, analyses incidents with AI, and optionally executes fixes with human approval.

![k8s-ops-agent architecture](architecture.png)

---

## What it does

Kubernetes clusters produce a constant stream of events. When a pod crashes, gets OOM-killed, or enters a CrashLoopBackOff, someone on call must manually correlate logs, events, and resource usage to find the root cause.

`k8s-ops-agent` automates this loop:

1. **Collector** — background thread polls the cluster every 30–60 seconds, filters `Warning` events (OOMKilled, CrashLoopBackOff, BackOff, Failed, Evicted), deduplicates by `resource_version`
2. **Agent** — LangChain ReAct agent (Claude) runs `get_pod_logs → describe_pod → list_events → get_node_status` in a Thought/Action/Observation loop
3. **Storage** — structured analysis saved to PostgreSQL (probable cause, evidence, affected resources, fix command)
4. **Dashboard** — light-theme web UI at `/` lists incidents in real time with status badges and expandable analysis cards
5. **API** — FastAPI serves incident reports; in autonomous mode, `POST /incidents/{id}/approve` executes the fix

---

## Architecture

```
K8s Cluster
    │ Warning events
    ▼
Collector (background thread)
    │ filter + deduplicate
    ▼
PostgreSQL — raw incident
    │
    ▼
ReAct Agent (LangChain + Claude)
    ├── get_pod_logs
    ├── describe_pod
    ├── list_events
    └── get_node_status (all read-only)
    │
    ▼
Analysis → PostgreSQL
    │
    ├── GET /            ← Dashboard UI (auto-refresh 30s)
    ├── GET /incidents   ← list + filter
    ├── GET /incidents/{id}      ← detail + analysis
    └── POST /incidents/{id}/approve ← execute fix (autonomous only)
```

---

## Stack

| Component | Library |
|---|---|
| API | FastAPI + Uvicorn |
| UI | Vanilla HTML/JS served by FastAPI StaticFiles |
| AI agent | LangChain + langchain-anthropic |
| LLM | Claude Haiku (configurable) |
| Kubernetes | `kubernetes` Python client |
| ORM | SQLAlchemy 2 |
| Database | PostgreSQL |
| Schema | Pydantic v2 |

---

## Project structure

```
k8s-ops-agent/
├── main.py           # FastAPI app + lifespan + UI route
├── collector.py      # K8s event poller — background thread
├── agent.py          # LangChain ReAct agent + analysis parser
├── k8s_tools.py      # Agent tools: logs, describe, events, nodes
├── database.py       # SQLAlchemy engine + session factory
├── models.py         # ORM model (Incident) + Pydantic schemas
├── static/
│   └── index.html    # Dashboard UI (light theme, auto-refresh)
├── k8s-test/
│   └── crashloop-pod.yaml  # Test workloads for local kind cluster
├── dev-setup.sh      # One-shot local env: kind + test pods + compose
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── SPEC.md
```

---

## Quick start

### Option A — with a real cluster

```bash
# 1. Copy and fill in your API key
cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY

# 2. Start the app + PostgreSQL
docker compose up --build

# 3. Open the dashboard
open http://localhost:8000
```

The agent connects to your local `~/.kube/config` by default. Inside a cluster it uses the in-cluster service account automatically.

### Option B — local kind cluster (no real cluster needed)

```bash
cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY

# Creates kind cluster, deploys crashy test pods, starts docker compose
KUBECONFIG_DIR=~/.kube-kind ./dev-setup.sh
```

`dev-setup.sh` provisions three pods that fail intentionally:
- `api-server-crashloop` — exits with code 1 (database connection refused)
- `worker-oomkilled` — OOMKilled by a 4Mi memory limit
- `frontend-bad-image` — ImagePullBackOff from a non-existent registry

The collector picks them up within one poll cycle and the agent analyses each.

---

## Dashboard

Open **http://localhost:8000** after starting the stack.

- Incident cards with status badges (analyzing / analyzed / fix_pending / fix_applied)
- Expandable analysis: probable cause, evidence, affected resources, suggested fix command
- Filter by status, auto-refresh every 30 seconds
- In autonomous mode: **Approve & Execute Fix** button per incident

![Dashboard — incident list](dashboard.png)

![Dashboard — analysis card expanded](dashboard2.png)

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/health` | Health check + current mode |
| `GET` | `/incidents` | List incidents (`?namespace=&status=`) |
| `GET` | `/incidents/{id}` | Incident detail + AI analysis |
| `POST` | `/incidents/{id}/approve` | Execute fix (autonomous mode only) |

### Example response — `GET /incidents/1`

```json
{
  "id": 1,
  "namespace": "production",
  "resource": "api-server-crashloop",
  "event_reason": "BackOff",
  "event_message": "Back-off restarting failed container api in pod ...",
  "status": "analyzed",
  "analysis": {
    "probable_cause": "The api-server container cannot connect to its database dependency, causing repeated crash loop restarts.",
    "evidence": [
      "Container restart count: 8 with CrashLoopBackOff status",
      "Pod logs show fatal error: 'database connection refused'",
      "ContainersReady condition is False"
    ],
    "affected_resources": [
      "api-server-crashloop pod (production namespace)",
      "Database service dependency (unreachable)"
    ],
    "fix_command": null
  },
  "created_at": "2024-11-01T14:23:00Z"
}
```

---

## Modes

| | Assisted (default) | Autonomous |
|---|---|---|
| Analyses incident | ✓ | ✓ |
| Suggests fix command | ✓ | ✓ |
| Executes fix automatically | ✗ | ✗ |
| Approve & Execute button | disabled | **enabled** |
| Config | `AGENT_MODE=assisted` | `AGENT_MODE=autonomous` |

In autonomous mode the fix only runs when a human clicks **Approve & Execute Fix** in the UI or calls `POST /incidents/{id}/approve`. Nothing executes without explicit approval.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `MODEL` | `claude-haiku-4-5-20251001` | Claude model ID |
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/k8sops` | PostgreSQL connection |
| `AGENT_MODE` | `assisted` | `assisted` or `autonomous` |
| `POLL_INTERVAL_SECONDS` | `60` | Event polling interval |
| `COLLECTOR_ENABLED` | `true` | Set to `false` for API-only mode |

---

## K8s tools (read-only)

| Tool | Input | Description |
|---|---|---|
| `get_pod_logs` | `pod-name/namespace` | Last 50 lines of container logs |
| `describe_pod` | `pod-name/namespace` | Phase, conditions, restart count, state |
| `list_events` | `namespace` | Last 20 Warning events |
| `get_node_status` | — | CPU + memory capacity/allocatable per node |

---

## Incident lifecycle

```
analyzing → analyzed → fix_pending → fix_applied
```

---

## License

MIT
