"""Lab 5's app: a small shop whose database is where things go wrong.

It has no OpenTelemetry code. The agent the Operator injects traces each request
and each query. These scenarios make Postgres the problem, so a trace shows that
a query was slow or failed, and Postgres's own logs and statistics show why.
"""

import asyncio
import logging
import os
import random
import threading
import time
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("shop")

DSN = os.environ["DATABASE_URL"]
SIGNOZ_URL = os.environ.get("SIGNOZ_URL", "http://signoz.localhost:8080")
CUSTOMERS = 50_000
# Longer than the collector's 10-second interval, so a sample lands during it.
HOLD_SECONDS = 15

TAKE_FROM_STOCK = "UPDATE stock SET qty = qty - 1 WHERE item = %s"


def random_email() -> str:
    return f"customer{random.randint(1, CUSTOMERS)}@example.com"


def place_order(item: str = "coffee") -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(TAKE_FROM_STOCK, (item,))
        conn.execute(
            "INSERT INTO sales (email, item, total, sold_at) VALUES (%s, %s, %s, now())",
            (random_email(), item, 4.50),
        )


def hold_row_during_payment() -> None:
    """Takes a row, then keeps the transaction open during a slow call."""
    with psycopg.connect(DSN) as conn:
        conn.execute(TAKE_FROM_STOCK, ("coffee",))
        log.info("waiting for the payment provider")
        # Deliberate bug: the row stays locked until this transaction ends.
        time.sleep(HOLD_SECONDS)


async def lock_wait() -> tuple[int, dict]:
    holder = asyncio.create_task(asyncio.to_thread(hold_row_during_payment))
    await asyncio.sleep(1)
    started = time.monotonic()
    await asyncio.to_thread(place_order)
    took = time.monotonic() - started
    await holder
    return 200, {"second_order_took_s": round(took, 1)}


def take_in_order(first: str, second: str, both_have_one: threading.Barrier) -> None:
    with psycopg.connect(DSN) as conn:
        conn.execute(TAKE_FROM_STOCK, (first,))
        both_have_one.wait(timeout=5)
        conn.execute(TAKE_FROM_STOCK, (second,))


async def deadlock() -> tuple[int, dict]:
    both_have_one = threading.Barrier(2)
    # Deliberate bug: two orders take the same rows in opposite orders.
    results = await asyncio.gather(
        asyncio.to_thread(take_in_order, "coffee", "bagel", both_have_one),
        asyncio.to_thread(take_in_order, "bagel", "coffee", both_have_one),
        return_exceptions=True,
    )
    failed = [result for result in results if isinstance(result, Exception)]
    if failed:
        log.error("order failed: %s", type(failed[0]).__name__)
        return 500, {"error": type(failed[0]).__name__, "failed_orders": len(failed)}
    return 200, {"failed_orders": 0}


def customer_history(email: str) -> tuple[int, float]:
    with psycopg.connect(DSN) as conn:
        # Deliberate bug: nothing indexes lower(email), so this reads the whole table.
        row = conn.execute(
            "SELECT count(*), coalesce(sum(total), 0) FROM sales WHERE lower(email) = %s", (email,)
        ).fetchone()
    return row[0], float(row[1])


async def missing_index() -> tuple[int, dict]:
    started = time.monotonic()
    sales, total = await asyncio.to_thread(customer_history, random_email())
    return 200, {"query_ms": round((time.monotonic() - started) * 1000), "sales": sales, "total": total}


def open_until_refused(held: list) -> str:
    while len(held) < 100:
        try:
            held.append(psycopg.connect(DSN))
        except psycopg.OperationalError as exc:
            return str(exc).strip().splitlines()[-1]
    return ""


async def too_many_clients() -> tuple[int, dict]:
    # Deliberate bug: connections are opened and kept, with no pool to limit them.
    held: list = []
    refusal = await asyncio.to_thread(open_until_refused, held)
    try:
        await asyncio.to_thread(place_order)
        order = "succeeded"
    except psycopg.OperationalError:
        order = "failed"
    await asyncio.sleep(HOLD_SECONDS)
    for conn in held:
        conn.close()
    if refusal:
        log.error("ran out of database connections after %d", len(held))
    return (503 if refusal else 200), {"connections_opened": len(held), "refused_with": refusal, "next_order": order}


SCENARIOS = {
    "lock_wait": (lock_wait, "One order keeps a row locked during a slow call, and the next order waits for it"),
    "deadlock": (deadlock, "Two orders take the same rows in opposite orders, so Postgres cancels one"),
    "missing_index": (missing_index, "Looks up one customer's sales in a table with no index for that"),
    "too_many_clients": (too_many_clients, "Opens connections until Postgres refuses, then tries to place an order"),
}

app = FastAPI(title="Lab 5 shop")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (Path(__file__).parent / "index.html").read_text().replace("__SIGNOZ_URL__", SIGNOZ_URL)


@app.post("/api/order")
def order() -> dict:
    """A normal request, when nothing is wrong."""
    place_order()
    return {"ok": True}


@app.get("/api/scenarios")
async def scenarios() -> list[dict]:
    return [{"name": name, "description": entry[1]} for name, entry in SCENARIOS.items()]


@app.post("/api/scenario/{name}")
async def run_scenario(name: str) -> JSONResponse:
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="unknown scenario")
    status, result = await SCENARIOS[name][0]()
    return JSONResponse({"scenario": name, "status": status, "result": result}, status_code=status)


@app.get("/api/load")
async def load_status() -> dict:
    """This lab has no load generator: each scenario makes its own traffic."""
    return {"running": False, "rps": 0, "error_pct": 0, "sent": 0, "uptime_s": 0}
