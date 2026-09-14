# k8s-ops-agent

> AIOps agent that monitors a Kubernetes cluster, analyses incidents with AI, and optionally executes fixes with human approval.

![k8s-ops-agent architecture](architecture.png)

---

## What it does

Kubernetes clusters produce a constant stream of events. When a pod crashes, gets OOM-killed, or enters a CrashLoopBackOff, someone on call must manually correlate logs, events, and resource usage to find the root cause.

`k8s-ops-agent` automates this loop:

1. **Collector** — background thread polls the cluster every 60 seconds, filters `Warning` events (OOMKilled, CrashLoopBackOff, BackOff, Failed, Evicted), deduplicates by `resource_version`
2. **Agent** — LangChain ReAct agent (Claude) runs `get_pod_logs → describe_pod → list_events → get_node_status` in a Thought/Action/Observation loop
3. **Storage** — structured analysis saved to PostgreSQL (probable cause, evidence, affected resources, fix command)
4. **API** — FastAPI serves incident reports; in autonomous mode, `POST /incidents/{id}/approve` executes the fix

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
    └── get_node_status
    │
    ▼
Analysis → PostgreSQL
    │
    ├── GET /incidents/{id}      ← assisted mode
    └── POST /incidents/{id}/approve ← autonomous mode
```

---

## Stack

| Component | Library |
|---|---|
| API | FastAPI + Uvicorn |
| AI agent | LangChain + langchain-anthropic |
| LLM | Claude (Haiku by default) |
| Kubernetes | `kubernetes` Python client |
| ORM | SQLAlchemy 2 |
| Database | PostgreSQL |
| Schema | Pydantic v2 |

---

## Quick start

```bash
# 1. Copy and fill in your API key
cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY

# 2. Start the app + PostgreSQL
docker compose up --build

# 3. Check health
curl http://localhost:8000/health

# 4. List incidents
curl http://localhost:8000/incidents
```

The agent connects to your local `~/.kube/config` by default. Inside a cluster it auto-detects the in-cluster service account.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/incidents` | List incidents (filter: `?namespace=&status=`) |
| `GET` | `/incidents/{id}` | Incident detail + AI analysis |
| `POST` | `/incidents/{id}/approve` | Execute fix (autonomous mode only) |

### Example response — `GET /incidents/1`

```json
{
  "id": 1,
  "namespace": "production",
  "resource": "api-server-7d9f8b-xkz4p",
  "event_reason": "OOMKilled",
  "event_message": "Container api was OOM killed",
  "status": "analyzed",
  "analysis": {
    "probable_cause": "Container exceeded its memory limit due to unbounded in-memory cache growth",
    "evidence": [
      "Exit code 137 (SIGKILL)",
      "Restart count: 8",
      "Memory request: 256Mi, limit: 512Mi"
    ],
    "affected_resources": ["api-server-7d9f8b-xkz4p"],
    "fix_command": "kubectl set resources deployment/api-server -c=api --limits=memory=1Gi -n production"
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
| Executes fix | ✗ | On `POST /approve` |
| Config | `AGENT_MODE=assisted` | `AGENT_MODE=autonomous` |

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `MODEL` | `claude-haiku-4-5-20251001` | Claude model ID |
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/k8sops` | PostgreSQL connection |
| `AGENT_MODE` | `assisted` | `assisted` or `autonomous` |
| `POLL_INTERVAL_SECONDS` | `60` | Event polling interval |
| `COLLECTOR_ENABLED` | `true` | Disable for API-only mode |

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
