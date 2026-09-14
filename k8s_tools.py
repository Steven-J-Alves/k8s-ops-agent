from langchain.tools import tool
from kubernetes import client, config


def _load_k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _parse_resource(resource_str: str) -> tuple[str, str]:
    """Parse 'pod-name/namespace' → (pod_name, namespace)."""
    parts = resource_str.strip().split("/")
    return parts[0], parts[1] if len(parts) > 1 else "default"


@tool
def get_pod_logs(pod_name_namespace: str) -> str:
    """Get the last 50 lines of logs from a pod. Input format: 'pod-name/namespace'"""
    try:
        _load_k8s()
        pod_name, namespace = _parse_resource(pod_name_namespace)
        v1 = client.CoreV1Api()
        logs = v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=50)
        return logs or "(no logs available)"
    except Exception as e:
        return f"Error getting logs: {e}"


@tool
def describe_pod(pod_name_namespace: str) -> str:
    """Describe a pod: phase, conditions, restart count, container state. Input format: 'pod-name/namespace'"""
    try:
        _load_k8s()
        pod_name, namespace = _parse_resource(pod_name_namespace)
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

        lines = [
            f"Pod: {pod.metadata.name}",
            f"Namespace: {pod.metadata.namespace}",
            f"Phase: {pod.status.phase}",
        ]

        for cs in pod.status.container_statuses or []:
            lines.append(f"Container: {cs.name} | Ready: {cs.ready} | Restarts: {cs.restart_count}")
            if cs.state.waiting:
                lines.append(f"  Waiting: {cs.state.waiting.reason} — {cs.state.waiting.message or ''}")
            if cs.state.terminated:
                lines.append(f"  Terminated: {cs.state.terminated.reason} (exit {cs.state.terminated.exit_code})")

        for cond in pod.status.conditions or []:
            lines.append(f"Condition: {cond.type}={cond.status}" + (f" — {cond.message}" if cond.message else ""))

        return "\n".join(lines)
    except Exception as e:
        return f"Error describing pod: {e}"


@tool
def list_events(namespace: str) -> str:
    """List the last 20 Warning events in a Kubernetes namespace."""
    try:
        _load_k8s()
        v1 = client.CoreV1Api()
        events = v1.list_namespaced_event(namespace=namespace.strip(), limit=50)

        lines = []
        for e in events.items:
            if e.type == "Warning":
                lines.append(f"[{e.reason}] {e.involved_object.name}: {e.message} (count={e.count})")

        return "\n".join(lines[:20]) if lines else "No warning events found in this namespace"
    except Exception as e:
        return f"Error listing events: {e}"


@tool
def get_node_status(dummy: str = "") -> str:
    """Get CPU and memory capacity and allocatable resources for all nodes."""
    try:
        _load_k8s()
        v1 = client.CoreV1Api()
        nodes = v1.list_node()

        lines = []
        for node in nodes.items:
            cap = node.status.capacity
            alloc = node.status.allocatable
            conditions = {c.type: c.status for c in node.status.conditions}
            lines.append(
                f"Node: {node.metadata.name} | Ready: {conditions.get('Ready', 'Unknown')} | "
                f"CPU: {alloc.get('cpu')}/{cap.get('cpu')} | "
                f"Memory: {alloc.get('memory')}/{cap.get('memory')}"
            )

        return "\n".join(lines) if lines else "No nodes found"
    except Exception as e:
        return f"Error getting node status: {e}"
