# backend/routes/pipeline_v7.py

from fastapi import APIRouter
import subprocess
import threading

# ---------------------------------------------------------
# Pipeline Router
# ---------------------------------------------------------
router = APIRouter(prefix="/pipeline", tags=["pipeline_v7"])

# ---------------------------------------------------------
# Run the v7 pipeline controller
# ---------------------------------------------------------

def _run_pipeline():
    subprocess.run(["python3", "/app/scripts/pipeline_controller_v7.py"], check=False)

@router.post("/run")
def run_pipeline():
    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()
    return {"status": "started"}
