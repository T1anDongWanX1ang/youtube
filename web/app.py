"""Minimal FastAPI app exposing on-demand single-video processing.

PredX ops calls ``POST /process-one`` with a YouTube URL; this transcribes the
video and extracts structured claims by reusing the existing services.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.process_one import process_one

logger = logging.getLogger(__name__)

app = FastAPI(
    title="YouTube Crypto - On-demand extraction",
    description="Transcribe a single YouTube video and extract structured claims.",
    version="0.1.0",
)


class ProcessOneRequest(BaseModel):
    url: str


@app.post("/process-one")
async def process_one_endpoint(req: ProcessOneRequest):
    """Extract one YouTube video into structured evidence."""
    try:
        return await process_one(req.url)
    except ValueError as e:
        # Bad/unparseable URL -> client error.
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception:  # noqa: BLE001 - surface upstream failures as 502
        # Genuine upstream extraction failure (fetch/transcribe/analyze). Log the
        # detail server-side; do not echo raw internals back to the caller.
        logger.exception("process_one failed for url=%s", req.url)
        return JSONResponse(
            status_code=502, content={"error": "extract failed: upstream processing error"}
        )
