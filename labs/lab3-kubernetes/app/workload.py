"""Lab 3's workload: a small service that misbehaves on request.

Each scenario causes a failure Kubernetes itself has to deal with, inside the
limits set in k8s/app.yaml. Like Lab 1, this code has no OpenTelemetry in it.

The same image also runs as the load generator, which calls GET /api/work.
"""

import asyncio
import contextvars
import logging
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

log = logging.getLogger("workload")
log.setLevel(logging.INFO)

MIB = 1024 * 1024
SCRATCH = Path(os.environ.get("SCRATCH_DIR", "/scratch"))
SIGNOZ_URL = os.environ.get("SIGNOZ_URL", "http://signoz.localhost:8080")
TOKEN_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
CA_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
API_SERVER = "https://kubernetes.default.svc"
NAMESPACE = os.environ.get("POD_NAMESPACE", "lab3")

# A separate process, so it competes for the container's CPU quota but not for
# this process's interpreter lock. Any slowdown here is then down to throttling.
BURN = "while True: sum(i * i for i in range(1000))"

state = {"healthy": True}
held_memory: list[bytes] = []
tasks: set[asyncio.Task] = set()


def start(coroutine) -> None:
    """Runs a scenario in the background, so the request returns straight away."""
    task = asyncio.create_task(coroutine, context=contextvars.Context())
    tasks.add(task)
    task.add_done_callback(tasks.discard)


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------


async def burn_cpu(seconds: int, workers: int) -> None:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    burners = [subprocess.Popen([sys.executable, "-c", BURN], env=env) for _ in range(workers)]
    log.warning("burning CPU with %d processes for %ds", workers, seconds)
    await asyncio.sleep(seconds)
    for burner in burners:
        burner.kill()
        burner.wait()
    log.warning("stopped burning CPU")


async def leak_memory(mib_per_second: int) -> None:
    """Grows until the kernel kills the container. There is no way back from this."""
    while True:
        # bytes() of repeated data touches every page, so it really uses memory.
        held_memory.append(b"x" * (mib_per_second * MIB))
        log.warning("holding %d MiB on purpose", len(held_memory) * mib_per_second)
        await asyncio.sleep(1)


async def fill_disk(mib: int, seconds: int) -> None:
    path = SCRATCH / "filler"
    chunk = b"\0" * MIB
    with path.open("wb") as file:
        for _ in range(mib):
            file.write(chunk)
        file.flush()
        os.fsync(file.fileno())
    log.warning("wrote %d MiB to %s, removing it in %ds", mib, path, seconds)
    await asyncio.sleep(seconds)
    path.unlink()
    log.warning("removed %s", path)


async def call_api_server(path: str, seconds: int, rps: int) -> None:
    """Calls the API server as this pod's ServiceAccount."""
    token = TOKEN_FILE.read_text()
    headers = {"Authorization": f"Bearer {token}"}
    statuses: dict[int, int] = {}
    deadline = time.monotonic() + seconds
    async with httpx.AsyncClient(base_url=API_SERVER, verify=CA_FILE, headers=headers, timeout=5) as client:
        while time.monotonic() < deadline:
            status = (await client.get(path)).status_code
            statuses[status] = statuses.get(status, 0) + 1
            await asyncio.sleep(1 / rps)
    log.warning("finished calling %s: %s", path, statuses)


class ScenarioIn(BaseModel):
    seconds: int = 120
    workers: int = 2
    mib: int = 512
    mib_per_second: int = 2
    rps: int = 20


def run_throttle(body: ScenarioIn) -> dict:
    start(burn_cpu(min(body.seconds, 300), min(body.workers, 4)))
    return {"burning_for_s": body.seconds}


def run_oom(body: ScenarioIn) -> dict:
    start(leak_memory(max(1, min(body.mib_per_second, 32))))
    return {"leaking_mib_per_s": body.mib_per_second}


def run_liveness(_body: ScenarioIn) -> dict:
    state["healthy"] = False
    log.error("health check now fails, so the kubelet should restart this container")
    return {"healthz": 503}


def run_disk(body: ScenarioIn) -> dict:
    start(fill_disk(min(body.mib, 1024), min(body.seconds, 300)))
    return {"writing_mib": body.mib}


def run_api_flood(body: ScenarioIn) -> dict:
    start(call_api_server(f"/api/v1/namespaces/{NAMESPACE}/pods", min(body.seconds, 300), min(body.rps, 50)))
    return {"rps": body.rps}


def run_api_denied(body: ScenarioIn) -> dict:
    # This pod's Role allows listing pods, and nothing else.
    start(call_api_server(f"/api/v1/namespaces/{NAMESPACE}/secrets", min(body.seconds, 300), min(body.rps, 50)))
    return {"rps": body.rps}


def run_log(_body: ScenarioIn) -> dict:
    # Written during the request, unlike the scenarios above, so it carries the
    # request's trace and span IDs. The extra= field shows what stdout loses.
    log.warning("one log line, written during the request", extra={"example.field": 42})
    return {"logged": 1}


SCENARIOS = {
    "throttle": (run_throttle, "Burns more CPU than the limit allows, so the kernel throttles the container"),
    "oom": (run_oom, "Leaks memory until the kernel kills the container"),
    "liveness": (run_liveness, "Makes /healthz fail, so the kubelet restarts the container"),
    "disk": (run_disk, "Writes 512 MiB to the node's disk, then removes it"),
    "api_flood": (run_api_flood, "Lists pods from the API server up to 20 times a second"),
    "api_denied": (run_api_denied, "Asks the API server for secrets it isn't allowed to read"),
    "log": (run_log, "Writes one log line during the request, linked to its trace"),
}


# --------------------------------------------------------------------------
# Load generator
# --------------------------------------------------------------------------


class LoadGen:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.rps = 0.0
        self.sent = 0
        self.started = 0.0

    def status(self) -> dict:
        return {
            "running": self.task is not None and not self.task.done(),
            "rps": self.rps,
            "error_pct": 0,
            "sent": self.sent,
            "uptime_s": round(time.time() - self.started) if self.started else 0,
        }


loadgen = LoadGen()


async def _loadgen_loop() -> None:
    target = os.environ.get("LOADGEN_TARGET", "http://127.0.0.1:8000")
    async with httpx.AsyncClient(base_url=target, timeout=15) as client:

        async def fire() -> None:
            try:
                await client.get("/api/work")
            except httpx.HTTPError:
                pass  # The target is often restarting in this lab.

        while True:
            asyncio.create_task(fire())
            loadgen.sent += 1
            await asyncio.sleep(1 / loadgen.rps)


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    SCRATCH.mkdir(exist_ok=True)
    yield


app = FastAPI(title="Lab 3 workload", lifespan=lifespan)


@app.get("/healthz")
async def healthz(response: Response) -> dict:
    if not state["healthy"]:
        response.status_code = 503
    return state


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (Path(__file__).parent / "index.html").read_text().replace("__SIGNOZ_URL__", SIGNOZ_URL)


@app.get("/api/work")
def work() -> dict:
    """A normal request: about 20 ms of CPU when nothing is wrong."""
    end = time.thread_time() + 0.02
    total = 0
    while time.thread_time() < end:
        total += sum(i * i for i in range(1000))
    return {"pod": os.environ.get("HOSTNAME", ""), "total": total}


@app.get("/api/scenarios")
async def scenarios() -> list[dict]:
    return [{"name": name, "description": entry[1]} for name, entry in SCENARIOS.items()]


@app.post("/api/scenario/{name}")
async def run_scenario(name: str, body: ScenarioIn | None = None) -> dict:
    if name not in SCENARIOS:
        raise HTTPException(status_code=404, detail="unknown scenario")
    return {"scenario": name, "result": SCENARIOS[name][0](body or ScenarioIn())}


class LoadIn(BaseModel):
    rps: float = 5
    error_pct: int = 0  # Accepted so the tutorial can use one panel for every lab.


@app.post("/api/load")
async def start_load(config: LoadIn) -> dict:
    if loadgen.task and not loadgen.task.done():
        loadgen.task.cancel()
    loadgen.rps = max(0.1, min(config.rps, 20))
    loadgen.sent = 0
    loadgen.started = time.time()
    # Use an empty context, so generated requests don't all join this request's trace.
    loadgen.task = asyncio.create_task(_loadgen_loop(), context=contextvars.Context())
    return loadgen.status()


@app.delete("/api/load")
async def stop_load() -> dict:
    if loadgen.task:
        loadgen.task.cancel()
        loadgen.task = None
    return loadgen.status()


@app.get("/api/load")
async def load_status() -> dict:
    return loadgen.status()
