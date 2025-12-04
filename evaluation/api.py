# evaluation/api.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
import uuid
import pathlib
import yaml
import shutil
import os
import asyncio

app = FastAPI()
BASE_DIR = pathlib.Path(__file__).resolve().parent
INCOMING_DIR = BASE_DIR / "incoming"
INCOMING_DIR.mkdir(parents=True, exist_ok=True)

@app.post("/evaluate")
async def evaluate(metadata: str = Form(...), file: UploadFile = File(...)):
    """
    Accepts:
     - metadata: YAML string with basic info
     - file: the model file
    Returns:
     - job_id
    """
    job_id = str(uuid.uuid4())
    job_dir = INCOMING_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        # save metadata
        meta_path = job_dir / "metadata.yaml"
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(metadata)

        # save file
        file_path = job_dir / file.filename
        with open(file_path, "wb") as out_f:
            shutil.copyfileobj(file.file, out_f)

        # Here: queue or spawn the evaluation worker (subprocess, celery, etc.)
        # For demo, we just create a "job" file and return success. Replace with real runner.
        # e.g., asyncio.create_task(run_measure(job_id, file_path, meta_path))

        return JSONResponse({"job_id": job_id}, status_code=202)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok"}
