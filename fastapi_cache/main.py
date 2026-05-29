import json
import sys
import time
import asyncio
import uuid
import logging

from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager 
from pydantic import BaseModel
sys.path.append(str(Path(__file__).resolve().parents[1]))
from client import Client
from fastapi_cache.fake_db import FAKE_DB
from fastapi_cache.config import Settings

# Load runtime configuration from environment-backed settings.
settings = Settings()




logging.basicConfig(
    level = logging.INFO,
    format = "%(message)s"
)

logger = logging.getLogger("fastapi_cache")

class UserUpdate(BaseModel):
    name:str
    role:str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize shared application resources on startup and clean them up
    during shutdown.

    The API owns one Redis-clone client connection for cache and queue
    operations, stored on app.state for route-level access.
    """

    host = settings.redis_host
    port = settings.redis_port
    
    for attempt in range(10):
        # Retry because Docker Compose may start the API before the Redis clone
        # is ready to accept TCP connections.

        try: 
            app.state.cache = Client(host = host, port=port)
            break
        except ConnectionRefusedError:
            await asyncio.sleep(1)
    
    else:
        raise RuntimeError("Could not connect to Redis clone")
    
    app.state.stats = {
        "hits": 0,
        "misses": 0,
    }
    yield

    app.state.cache.close()


app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    Add request-level observability around every HTTP request.

    Generates a correlation ID, measures end-to-end request latency,
    emits structured JSON logs, and returns the request ID to clients.
    """
    
    request_id = str(uuid.uuid4())
    start = time.perf_counter()

    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    logger.info(json.dumps({
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
        "client_host": request.client.host if request.client else None,
    }))

    response.headers["X-Request-ID"] = request_id

    return response

@app.put("/users/{user_id}")
def update_user(user_id: str, updated_user: UserUpdate, request:Request):
    """
    Update the backing datastore and invalidate the cached user record.

    This preserves cache-aside correctness by ensuring future reads
    fetch fresh data from the database path.
    """
    
    cache = request.app.state.cache 

    if user_id not in FAKE_DB:
        raise HTTPException(status_code=404, detail="User not found")
    
    FAKE_DB[user_id] = {
        "id": int(user_id),
        "name": updated_user.name,
        "role": updated_user.role,
    }

    cache_key = f"user:{user_id}"
    cache.delete(cache_key)

    return {
        "message": "User updated",
        "cache_invalidated": "True",
        "data": FAKE_DB[user_id],
    }

@app.get("/users/{user_id}")
def get_user(user_id: str, request: Request):
    """
    Read user data through a cache-aside pattern.

    The API checks cache first, falls back to the backing datastore on
    misses, then stores the result with a TTL for future requests.
    """

    start = time.perf_counter()
    cache = request.app.state.cache
    stats = request.app.state.stats

    cache_key = f"user:{user_id}"
    cached_user = cache.get(cache_key)

    if cached_user is not None:
        stats["hits"] +=1
        duration_ms = round((time.perf_counter() - start) *1000,2)
        return {
            "source":"cache",
            "duration_ms": duration_ms,
            "data": json.loads(cached_user.decode("utf-8")),
        }
    
    stats["misses"] +=1 
    time.sleep(1)
    user = FAKE_DB.get(user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    cache.set(cache_key, json.dumps(user), "EX", str(settings.cache_ttl))
    duration_ms = round((time.perf_counter() - start) *1000,2)

    return {
        "source": "database",
        "duration_ms": duration_ms,
        "data": user,
    }


@app.get("/cache/stats")
def cache_stats(request: Request):
    """
    Return process local cach hit/miss metrics for basic observability
    """
    stats = request.app.state.stats
    time.sleep(1)
    return stats

@app.delete("/cache/users/{user_id}")
def invalidate_user_cache(user_id: str, request: Request):
    """
    Manually remove a user cache entry.

    Useful for testing cache invalidation and simulating explicit
    administrative cache eviction.
    """
    
    cache = request.app.state.cache
    
    cache_key = f"user:{user_id}"

    deleted = cache.delete(cache_key)

    time.sleep(1)
    return {
        "cache_key": cache_key,
        "deleted": bool(deleted),
    }

@app.get("/health")
def health_check(request:Request):
    """
    Report API health and dependency health.

    The API is considered alive if this route can execute. The overall
    status is degraded when the Redis clone dependency is unavailable.
    """

    cache = request.app.state.cache

    try:
        pong = cache.ping()
        cache_status = "healthy" if pong == b"PONG" else "unhealthy"
    
    except Exception:
        cache_status = "unhealthy"

    overall_status = "healthy" if cache_status == "healthy" else "degraded"
    
    return {
        "status": overall_status,
        "api": "healthy",
        "cache": cache_status,
    }

@app.post("/jobs")
def create_job(request:Request):
    """
    Submit a job into the Redis-backed queue.

    The API acts as the producer: it creates job metadata, stores initial
    job state, and enqueues the job ID for a separate worker process.
    """
    queue_size = cache.llen("jobs")

    if queue_size >= settings.max_queue_size:
        raise HTTPException(
            status_code=429,
            detail="Queue is full. retry later."
        )
    
    cache = request.app.state.cache

    job_id = str(uuid.uuid4())
    job_key = f"job:{job_id}"

    job_data = {
        "id": job_id,
        "status": "queued",
        "type": "demo_task",
        "created_at": now_iso(),
        "started_at":None,
        "completed_at": None,
        "failed_at": None,
        "error": None,
        "result": None,
        "attempts": 0,
        "max_attempts": 3,
    }

    cache.set(job_key, json.dumps(job_data))
    cache.lpush("jobs", job_id)

    return {
        "job_id": job_id,
        "status": "queued",
    }

@app.get("/jobs/metrics")
def get_job_metrics(request: Request):
    cache = request.app.state.cache
    processed = cache.get("metrics:processed_jobs")
    failed = cache.get("metrics:failed_jobs")

    return {
        "queued_jobs": cache.llen("jobs"),
        "dead_jobs": cache.llen("dead_jobs"),
        "processed_jobs": int(processed.decode("utf-8")) if processed else 0,
        "failed_jobs": int(failed.decode("utf-8")) if failed else 0,
        "max_queue_size": settings.max_queue_size,
    }

@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    cache = request.app.state.cache

    job_key = f"job:{job_id}"
    job = cache.get(job_key)

    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return json.loads(job.decode("utf-8"))

@app.get("/jobs/dead/count")
def get_dead_jobs_count(request: Request):
    cache = request.app.state.cache

    return {
        "dead_jobs": cache.llen("dead_jobs")
    }




def now_iso():
    return datetime.now(timezone.utc).isoformat()