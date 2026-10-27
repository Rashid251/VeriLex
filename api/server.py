# api/server.py
# Thin HTTP wrapper around the existing CRAG graph, so the React frontend
# can ask questions the same way main.py does, over an API instead of stdin.

# Windows long-path workaround: prefix sys.path entries with \\?\ so that
# Python can load deeply-nested packages in a long working directory without
# hitting the 260-character MAX_PATH limit.
import sys
if sys.platform == "win32":
    sys.path = [
        "\\\\?\\" + p if ":" in p and not p.startswith("\\\\?\\") else p
        for p in sys.path
    ]

import os
import json
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from graph.graph import run, graph, build_initial_state
from rag.chat_model import reset_token_count, get_token_count
from backend.db import create_tables
from backend.routes_auth import router as auth_router

app = FastAPI(title="VeriLex API", version="1.0.0")

# ------------------------------------------------------------------
# CORS — allow_credentials=True is required for HttpOnly cookie auth.
# Never use allow_origins=["*"] together with allow_credentials=True;
# always list explicit origins.
# FRONTEND_URL may be comma-separated to allow multiple origins, e.g.:
#   FRONTEND_URL=https://verilex.vercel.app,http://localhost:5173
# ------------------------------------------------------------------
_raw_frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
_origins: list[str] = [o.strip() for o in _raw_frontend_url.split(",") if o.strip()]
# Always include local dev origins so developers don't need to set FRONTEND_URL locally
for _local in ["http://localhost:5173", "http://127.0.0.1:5173"]:
    if _local not in _origins:
        _origins.append(_local)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Auth routes (/auth/signup, /auth/login, /auth/logout, /auth/me)
# ------------------------------------------------------------------
app.include_router(auth_router)

# ------------------------------------------------------------------
# Database initialisation — runs once on startup, never drops tables
# ------------------------------------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    create_tables()


# ------------------------------------------------------------------
# Health endpoint — used by Render health checks and monitoring
# ------------------------------------------------------------------
@app.get("/health", tags=["ops"])
def health() -> dict:
    """Return a simple liveness signal. Does not touch the database."""
    return {"status": "ok"}


# ------------------------------------------------------------------
# CRAG / RAG endpoints (unchanged behaviour)
# ------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


@app.post("/ask", tags=["rag"])
def ask(request: AskRequest):
    """Run the full CRAG pipeline and return a single JSON response."""
    start = time.perf_counter()
    result = run(request.question)
    elapsed = time.perf_counter() - start

    return {
        "answer": result["answer"],
        "documents": result["documents"],
        "document_grades": result["document_grades"],
        "status": result["status"],
        "retrieval_retries": result["retrieval_retries"],
        "validation_retries": result["validation_retries"],
        "total_tokens": get_token_count(),
        "total_time": round(elapsed, 1),
    }


@app.post("/ask/stream", tags=["rag"])
def ask_stream(request: AskRequest):
    """Run the CRAG pipeline and stream one Server-Sent Event per graph node."""

    def event_generator():
        reset_token_count()
        start = time.perf_counter()
        initial_state = build_initial_state(request.question)
        final_state = initial_state

        for chunk in graph.stream(initial_state, stream_mode="updates"):
            node_name, state_snapshot = next(iter(chunk.items()))
            final_state = state_snapshot

            event = {
                "type": "step",
                "node": node_name,
                "question": state_snapshot.get("question", ""),
                "retrieval_retries": state_snapshot.get("retrieval_retries", 0),
                "validation_retries": state_snapshot.get("validation_retries", 0),
                "document_grades": state_snapshot.get("document_grades", []),
            }
            yield f"data: {json.dumps(event)}\n\n"

        elapsed = time.perf_counter() - start
        done_event = {
            "type": "done",
            "answer": final_state["answer"],
            "documents": final_state["documents"],
            "document_grades": final_state["document_grades"],
            "status": final_state["status"],
            "retrieval_retries": final_state["retrieval_retries"],
            "validation_retries": final_state["validation_retries"],
            "total_tokens": get_token_count(),
            "total_time": round(elapsed, 1),
        }
        yield f"data: {json.dumps(done_event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
