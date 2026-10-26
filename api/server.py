# api/server.py
# Thin HTTP wrapper around the existing CRAG graph, so the React frontend
# can ask questions the same way main.py does, over an API instead of stdin.

import sys
if sys.platform == "win32":
    sys.path = ["\\\\?\\" + p if ":" in p and not p.startswith("\\\\?\\") else p for p in sys.path]

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

app = FastAPI(title="VeriLex API")

# ------------------------------------------------------------------
# CORS — must include credentials support for cookie-based auth
# ------------------------------------------------------------------
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
origins = [origin.strip() for origin in FRONTEND_URL.split(",") if origin.strip()]
for default_origin in ["http://localhost:5173", "http://127.0.0.1:5173"]:
    if default_origin not in origins:
        origins.append(default_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,          # required for cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------
app.include_router(auth_router)

# ------------------------------------------------------------------
# Database initialisation (safe — only creates tables that don't exist)
# ------------------------------------------------------------------
@app.on_event("startup")
def startup():
    create_tables()


# ------------------------------------------------------------------
# CRAG endpoints (unchanged)
# ------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


@app.post("/ask")
def ask(request: AskRequest):
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


@app.post("/ask/stream")
def ask_stream(request: AskRequest):
    # same pipeline as /ask, but emits one event per graph node as it finishes,
    # so the frontend can show retrieval/grading/rewriting/validation live instead
    # of a blank screen until the whole run completes.
    def event_generator():
        reset_token_count()
        start = time.perf_counter()
        initial_state = build_initial_state(request.question)
        final_state = initial_state

        for chunk in graph.stream(initial_state, stream_mode="updates"):
            node_name, state_snapshot = next(iter(chunk.items()))
            final_state = state_snapshot
            # each node function returns the full state dict, not a diff,
            # so state_snapshot already reflects everything up to this step

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
