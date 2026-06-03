import json
import time
import asyncio
import uuid
import logging

from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager 
from pydantic import BaseModel, Field
from redis_clone.client import Client
from redis_clone.exceptions import CommandError
from fastapi_cache.fake_db import FAKE_DB
from fastapi_cache.config import Settings
from fastapi.responses import PlainTextResponse
from typing import Literal

class InferenceRequest(BaseModel):
    prompt: str = Field(
        min_length =1,
        max_length = 1000,
    )

    provider: Literal["fake", "huggingface"] = "fake"


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
    time.sleep(settings.demo_db_delay_seconds)
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

    enqueue_job(cache, job_id, job_key, job_data)

    return {
        "job_id": job_id,
        "status": "queued",
    }

@app.get("/jobs/metrics")
def get_job_metrics(request: Request):
    cache = request.app.state.cache
    
    processed = cache.get("metrics:processed_jobs")
    failed = cache.get("metrics:failed_jobs")
    semantic_hits = cache.get("metrics:semantic_cache_hits")
    semantic_misses = cache.get("metrics:semantic_cache_misses")

    faiss_search_count = cache.get("metrics:faiss_search_count")
    linear_search_count = cache.get("metrics:linear_search_count")

    faiss_search_count = decode_counter(faiss_search_count)
    linear_search_count = decode_counter(linear_search_count)
    provider_call_count = cache.get("metrics:provider_call_count")
    provider_call_count = decode_counter(provider_call_count)

    faiss_search_latency_total = cache.get("metrics:faiss_search_latency_ms_total")
    linear_search_latency_total = cache.get("metrics:linear_search_latency_ms_total")
    provider_latency_total = cache.get("metrics:provider_latency_ms_total")

    faiss_search_latency_ms_total = decode_counter(faiss_search_latency_total)
    linear_search_latency_ms_total = decode_counter(linear_search_latency_total)
    provider_latency_ms_total = decode_counter(provider_latency_total)
    faiss_search_latency_ms_avg = (
        faiss_search_latency_ms_total / faiss_search_count
        if faiss_search_count
        else 0
    )
    linear_search_latency_ms_avg = (
        linear_search_latency_ms_total / linear_search_count
        if linear_search_count
        else 0
    )
    provider_latency_ms_avg = (
        provider_latency_ms_total / provider_call_count
        if provider_call_count
        else 0
    )

    processed_count = decode_counter(processed)

    semantic_hits_count = decode_counter(semantic_hits)
    semantic_misses_count = decode_counter(semantic_misses)

    total_semantic_requests = semantic_hits_count + semantic_misses_count

    semantic_hit_rate = (
        semantic_hits_count / total_semantic_requests
        if total_semantic_requests > 0 
        else 0
    )

    return {
        "queued_jobs": cache.llen("jobs"),
        "processing_jobs": cache.llen("processing_jobs"),
        "dead_jobs": cache.llen("dead_jobs"),
        "processed_jobs": processed_count,
        "failed_jobs": decode_counter(failed),
        "max_queue_size": settings.max_queue_size,
        "semantic_cache_hits": semantic_hits_count,
        "semantic_cache_misses": semantic_misses_count,
        "semantic_cache_hit_rate": round(semantic_hit_rate,4),
        "faiss_search_count": faiss_search_count,
        "faiss_search_latency_ms_total": faiss_search_latency_ms_total,
        "faiss_search_latency_ms_avg": round(faiss_search_latency_ms_avg, 2),
        "linear_search_count": linear_search_count,
        "linear_search_latency_ms_total": linear_search_latency_ms_total,
        "linear_search_latency_ms_avg": round(linear_search_latency_ms_avg, 2),
        "provider_call_count": provider_call_count,
        "provider_latency_ms_total": provider_latency_ms_total,
        "provider_latency_ms_avg": round(provider_latency_ms_avg, 2),
    }

@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(request: Request):
    data = get_job_metrics(request)

    lines = []

    for key, value in data.items():
        if isinstance(value, (int, float)):
            lines.append(f"mini_redis_{key} {value}")

    return "\n".join(lines) + "\n"


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

@app.post("/inference")
def create_inference_request(payload: InferenceRequest, request: Request):
    cache = request.app.state.cache
    job_id = str(uuid.uuid4())
    job_key = f"job:{job_id}"

    job_data = {
        "id": job_id,
        "status": "queued",
        "type": "inference",
        "prompt": payload.prompt,
        "provider": payload.provider,
        "created_at": now_iso(),
        "started_at": None,
        "completed_at": None,
        "failed_at": None,
        "error": None,
        "result": None,
        "attempts": 0,
        "max_attempts": 3,
    }

    enqueue_job(cache, job_id, job_key, job_data)

    return {
        "job_id": job_id,
        "status": "queued",
        "type": "inference",
    }


def enqueue_job(cache, job_id, job_key, job_data):
    try:
        cache.enqueue(
            "jobs",
            job_id,
            job_key,
            json.dumps(job_data),
            settings.max_queue_size,
        )
    except CommandError as exc:
        if exc.args and exc.args[0] == b"queue is full":
            raise HTTPException(
                status_code=429,
                detail="Queue is full. Please retry later.",
            )

        raise


def decode_counter(raw, default=0):
    if raw is None:
        return default

    try:
        return int(raw.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, ValueError):
        return default


def now_iso():
    return datetime.now(timezone.utc).isoformat()
