"""FastAPI streaming backend for the data assistant.

POST /ask  -> Server-Sent Events stream:
  status  : progress label ("Writing SQL…", "Running query…", "Summarizing…")
  sql     : the generated SQL
  refused : grounded refusal (unsafe SQL)
  error   : model/query error
  table   : {columns, rows} of the (capped) result
  token   : a chunk of the streamed, grounded answer
  empty   : no rows matched
  done    : end of stream
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import core

app = FastAPI(title="PgBigData Assistant")


class AskReq(BaseModel):
    question: str


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/health")
def health():
    return {"ok": True, "model": core.model_name(),
            "openai": bool(os.environ.get("OPENAI_API_KEY"))}


@app.post("/ask")
def ask(req: AskReq):
    def gen():
        q = (req.question or "").strip()
        if not q:
            yield _sse("error", "Please enter a question.")
            return
        if not os.environ.get("OPENAI_API_KEY"):
            yield _sse("error", "OPENAI_API_KEY is not set on the server.")
            return

        yield _sse("status", "Writing SQL")
        try:
            schema = core.build_schema()
            sql = core.generate_sql(q, schema)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", f"Could not reach the model: {exc}")
            return
        yield _sse("sql", sql)

        ok, why = core.is_safe(sql)
        if not ok:
            yield _sse("refused", f"I only run read-only queries — {why}.")
            return

        yield _sse("status", "Running query")
        try:
            cols, rows = core.run_readonly(sql)
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", f"The query failed: {exc}")
            return

        yield _sse("table", {"columns": cols, "rows": rows})
        if not rows:
            yield _sse("empty", "I found no matching rows, so I can't answer that — I won't guess.")
            yield _sse("done", "")
            return

        yield _sse("status", "Summarizing")
        try:
            preview = core.rows_to_csv(cols, rows, limit=100)
            for chunk in core.summarize_stream(q, preview):
                yield _sse("token", chunk)
        except Exception:  # noqa: BLE001
            pass
        yield _sse("done", "")

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
