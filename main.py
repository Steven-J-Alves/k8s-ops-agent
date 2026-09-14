import logging
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from collector import start_collector
from database import create_tables, get_db
from models import Incident, IncidentResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    start_collector()
    yield


app = FastAPI(title="k8s-ops-agent", version="1.0.0", lifespan=lifespan)

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(str(_STATIC / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "mode": os.getenv("AGENT_MODE", "assisted")}


@app.get("/incidents", response_model=list[IncidentResponse])
def list_incidents(
    namespace: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Incident)
    if namespace:
        query = query.filter(Incident.namespace == namespace)
    if status:
        query = query.filter(Incident.status == status)
    return query.order_by(Incident.created_at.desc()).limit(100).all()


@app.get("/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.post("/incidents/{incident_id}/approve", response_model=IncidentResponse)
def approve_fix(incident_id: int, db: Session = Depends(get_db)):
    if os.getenv("AGENT_MODE", "assisted") != "autonomous":
        raise HTTPException(status_code=403, detail="Autonomous mode is disabled. Set AGENT_MODE=autonomous to enable.")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != "analyzed":
        raise HTTPException(status_code=409, detail=f"Incident status is '{incident.status}', expected 'analyzed'")

    analysis = incident.analysis or {}
    fix_command = analysis.get("fix_command")
    if not fix_command:
        raise HTTPException(status_code=422, detail="No fix command available for this incident")

    incident.status = "fix_pending"
    incident.updated_at = datetime.now(timezone.utc)
    db.commit()

    try:
        result = subprocess.run(
            fix_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info("Fix command output: %s", result.stdout)
        if result.returncode != 0:
            logger.error("Fix command stderr: %s", result.stderr)
    except subprocess.TimeoutExpired:
        logger.error("Fix command timed out: %s", fix_command)

    incident.status = "fix_applied"
    incident.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(incident)
    return incident
