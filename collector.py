import logging
import os
import threading
import time
from datetime import datetime, timezone

from kubernetes import client, config

from agent import analyze_incident
from database import SessionLocal
from models import Incident

logger = logging.getLogger(__name__)

_WATCHED_REASONS = {"OOMKilled", "CrashLoopBackOff", "BackOff", "Failed", "Evicted"}
_seen: set[str] = set()


def _load_k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _collect_once():
    try:
        _load_k8s()
        v1 = client.CoreV1Api()
        events = v1.list_event_for_all_namespaces(limit=200)
    except Exception as e:
        logger.error("Failed to list events: %s", e)
        return

    for event in events.items:
        if event.type != "Warning":
            continue
        if event.reason not in _WATCHED_REASONS:
            continue

        key = event.metadata.resource_version
        if key in _seen:
            continue
        _seen.add(key)

        namespace = event.metadata.namespace
        resource = event.involved_object.name
        reason = event.reason
        message = event.message or ""

        logger.info("New incident: [%s] %s/%s — %s", reason, namespace, resource, message[:80])

        db = SessionLocal()
        try:
            incident = Incident(
                namespace=namespace,
                resource=resource,
                event_reason=reason,
                event_message=message,
                status="analyzing",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(incident)
            db.commit()
            db.refresh(incident)
            incident_id = incident.id
        finally:
            db.close()

        try:
            analysis = analyze_incident(namespace, resource, reason, message)
        except Exception as e:
            logger.error("Agent failed for incident %d: %s", incident_id, e)
            analysis = None

        db = SessionLocal()
        try:
            row = db.query(Incident).filter(Incident.id == incident_id).first()
            if row:
                row.analysis = analysis
                row.status = "analyzed"
                row.updated_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()


def start_collector():
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    enabled = os.getenv("COLLECTOR_ENABLED", "true").lower() == "true"

    if not enabled:
        logger.info("Collector disabled (COLLECTOR_ENABLED=false)")
        return

    def _loop():
        logger.info("Collector started, polling every %ds", interval)
        while True:
            _collect_once()
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="k8s-collector")
    t.start()
