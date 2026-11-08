"""frontend service for Lab 2: Lab 1's frontend, plus a few OpenTelemetry API calls.

The OpenTelemetry Operator injects the agent, exactly as in Lab 1, so there is no
SDK setup here. This file only uses the API, to add what the agent can't know:
  - lab.scenario on the automatic server span
  - the scenario.runs metric
  - the trace ID in API responses
"""

import asyncio
import contextvars
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from opentelemetry import metrics, trace
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

log = logging.getLogger("frontend")
meter = metrics.get_meter("lab.frontend")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
SIGNOZ_URL = os.environ.get("SIGNOZ_URL", "http://signoz.localhost:8080")

backend = httpx.AsyncClient(base_url=BACKEND_URL, timeout=5.0)

scenario_runs = meter.create_counter(
    "scenario.runs", unit="{run}", description="Scenario executions by outcome"
)


# --------------------------------------------------------------------------
# Scenarios. Each one is a coroutine returning a JSON-able result, or raising
# HTTPException for a controlled error response.
# --------------------------------------------------------------------------

ITEMS = ["coffee", "bagel", "sandwich", "cake"]


async def s_order(_p: dict) -> dict:
    r = await backend.post("/orders", json={"item": random.choice(ITEMS), "qty": random.randint(1, 5)})
    r.raise_for_status()
    return r.json()


async def s_list(_p: dict) -> dict:
    r = await backend.get("/orders")
    r.raise_for_status()
    return {"orders": len(r.json())}


async def s_slow(_p: dict) -> dict:
    r = await backend.get("/work/slow")
    r.raise_for_status()
    return r.json()


async def s_bad_input(_p: dict) -> dict:
    log.warning("rejected order: qty must be positive", extra={"order.qty": -3})
    raise HTTPException(status_code=400, detail="qty must be positive")


async def s_crash(_p: dict) -> dict:
    basket = {"items": 0}
    return {"avg": 100 / basket["items"]}  # ZeroDivisionError -> unhandled 500


async def s_backend_500(_p: dict) -> dict:
    r = await backend.get("/work/fail")
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.error("backend call failed: %s", exc)
        raise HTTPException(status_code=502, detail="backend failed") from exc
    return r.json()


async def s_timeout(_p: dict) -> dict:
    try:
        r = await backend.get("/work/slow", params={"ms": 3000}, timeout=1.0)
    except httpx.ReadTimeout as exc:
        log.error("backend timed out after 1s")
        raise HTTPException(status_code=504, detail="backend timeout") from exc
    return r.json()


async def s_slow_query(_p: dict) -> dict:
    r = await backend.get("/work/slow-query", params={"seconds": 2})
    r.raise_for_status()
    return r.json()


async def s_db_error(_p: dict) -> dict:
    r = await backend.get("/work/db-error")
    if r.status_code >= 500:
        log.error("backend reported a database error")
        raise HTTPException(status_code=502, detail="database error in backend")
    return r.json()


async def s_cpu_burn(p: dict) -> dict:
    seconds = float(p.get("seconds", 10))
    r = await backend.get("/work/cpu", params={"seconds": seconds}, timeout=seconds + 5)
    r.raise_for_status()
    return r.json()


async def s_log_burst(p: dict) -> dict:
    count = min(int(p.get("count", 20)), 1000)
    level = getattr(logging, str(p.get("level", "INFO")).upper(), logging.INFO)
    for i in range(count):
        log.log(level, "log burst line %d of %d", i + 1, count, extra={"burst.index": i, "burst.size": count})
    return {"emitted": count, "level": logging.getLevelName(level)}


async def s_slow_item(_p: dict) -> dict:
    # Five orders. Only the catering ones hit the slow pricing bug.
    results = []
    for item in ["coffee", "catering", "bagel", "catering", "cake"]:
        r = await backend.post("/orders", json={"item": item, "qty": 1})
        r.raise_for_status()
        results.append(r.json())
    return {"orders": len(results)}


async def s_free_orders(_p: dict) -> dict:
    # Five orders using a coupon. All succeed, and all come out free.
    totals = []
    for _ in range(5):
        order = {"item": random.choice(ITEMS), "qty": random.randint(1, 5), "coupon": "SAVE10"}
        r = await backend.post("/orders", json=order)
        r.raise_for_status()
        totals.append(r.json()["total"])
    return {"orders": len(totals), "revenue": sum(totals)}


async def s_cache_miss(_p: dict) -> dict:
    # Six catalogue lookups. Some miss the cache and take the slow path.
    for item in ITEMS + ITEMS[:2]:
        r = await backend.get("/catalog", params={"item": item})
        r.raise_for_status()
    return {"lookups": 6}


SCENARIOS = {
    "order": (s_order, "Place an order: frontend → backend → Postgres INSERT. Happy path."),
    "list": (s_list, "List orders: frontend → backend → Postgres SELECT."),
    "slow": (s_slow, "Backend sleeps 1–3 s. Latency spike, no error."),
    "bad_input": (s_bad_input, "Frontend rejects input with 400 + WARN log. Client error, not a server error."),
    "crash": (s_crash, "Unhandled ZeroDivisionError in frontend → 500."),
    "backend_500": (s_backend_500, "Backend raises unhandled exception → 500; frontend answers 502."),
    "timeout": (s_timeout, "Backend takes 3 s, frontend gives up after 1 s → 504."),
    "slow_query": (s_slow_query, "Backend runs SELECT pg_sleep(2). Slow DB span."),
    "db_error": (s_db_error, "Backend queries a missing table; logs ERROR with traceback → 500/502."),
    "cpu_burn": (s_cpu_burn, "Backend burns CPU for N seconds (default 10). Visible in pod CPU metrics."),
    "log_burst": (s_log_burst, "Emit N log lines at a chosen level, with attributes."),
    "slow_item": (s_slow_item, "Five orders. One product is slow, and nothing fails."),
    "free_orders": (s_free_orders, "Five orders with a coupon. Everything succeeds, but revenue is zero."),
    "cache_miss": (s_cache_miss, "Six catalogue lookups. Some are slow, for no visible reason."),
}


# --------------------------------------------------------------------------
# Load generator: background traffic so dashboards and alerts have data.
# --------------------------------------------------------------------------

OK_MIX = ["order"] * 6 + ["list"] * 3 + ["slow"]
ERROR_MIX = ["backend_500", "db_error", "timeout", "crash", "bad_input"]


class LoadGen:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.rps = 0.0
        self.error_pct = 0
        self.sent = 0
        self.started = 0.0

    def status(self) -> dict:
        return {
            "running": self.task is not None and not self.task.done(),
            "rps": self.rps,
            "error_pct": self.error_pct,
            "sent": self.sent,
            "uptime_s": round(time.time() - self.started) if self.started else 0,
        }


loadgen = LoadGen()


async def _loadgen_loop() -> None:
    sem = asyncio.Semaphore(30)
    async with httpx.AsyncClient(base_url=os.environ.get("LOADGEN_TARGET", "http://127.0.0.1:8000"), timeout=15) as client:

        async def fire(name: str) -> None:
            async with sem:
                try:
                    await client.post(f"/api/scenario/{name}", json={})
                except httpx.HTTPError:
                    pass

        while True:
            mix = ERROR_MIX if random.uniform(0, 100) < loadgen.error_pct else OK_MIX
            asyncio.create_task(fire(random.choice(mix)))
            loadgen.sent += 1
            await asyncio.sleep(1 / loadgen.rps)


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if loadgen.task:
        loadgen.task.cancel()
    await backend.aclose()


app = FastAPI(title="frontend", lifespan=lifespan)


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Common app pattern: log unhandled errors and return JSON.
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"status": 500, "error": repr(exc), "trace_id": current_trace_id()}, status_code=500)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html = (Path(__file__).parent / "index.html").read_text()
    return html.replace("__SIGNOZ_URL__", SIGNOZ_URL)


@app.get("/api/scenarios")
async def list_scenarios() -> list[dict]:
    return [{"name": k, "description": v[1]} for k, v in SCENARIOS.items()]


@app.post("/api/scenario/{name}")
async def run_scenario(name: str, request: Request) -> JSONResponse:
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail=f"unknown scenario {name}")
    try:
        params = await request.json()
    except ValueError:
        params = {}
    fn = SCENARIOS[name][0]
    trace_id = current_trace_id()
    trace.get_current_span().set_attribute("lab.scenario", name)
    try:
        result = await fn(params or {})
    except HTTPException as exc:
        scenario_runs.add(1, {"scenario": name, "outcome": "error"})
        return JSONResponse(
            {"scenario": name, "status": exc.status_code, "error": exc.detail, "trace_id": trace_id},
            status_code=exc.status_code,
        )
    except Exception:
        scenario_runs.add(1, {"scenario": name, "outcome": "error"})
        raise
    scenario_runs.add(1, {"scenario": name, "outcome": "ok"})
    return JSONResponse({"scenario": name, "status": 200, "result": result, "trace_id": trace_id})


class LoadIn(BaseModel):
    rps: float = 5
    error_pct: int = 10


@app.post("/api/load")
async def start_load(cfg: LoadIn) -> dict:
    if loadgen.task and not loadgen.task.done():
        loadgen.task.cancel()
    loadgen.rps = max(0.1, min(cfg.rps, 100))
    loadgen.error_pct = max(0, min(cfg.error_pct, 100))
    loadgen.sent = 0
    loadgen.started = time.time()
    # Use an empty context, so generated requests don't all join this request's trace.
    loadgen.task = asyncio.create_task(_loadgen_loop(), context=contextvars.Context())
    log.info("load generator started", extra={"loadgen.rps": loadgen.rps, "loadgen.error_pct": loadgen.error_pct})
    return loadgen.status()


@app.delete("/api/load")
async def stop_load() -> dict:
    if loadgen.task:
        loadgen.task.cancel()
        loadgen.task = None
    log.info("load generator stopped", extra={"loadgen.sent": loadgen.sent})
    return loadgen.status()


@app.get("/api/load")
async def load_status() -> dict:
    return loadgen.status()

