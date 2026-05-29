import json
import sys
import time
import os 
import asyncio
import uuid
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager 
from pydantic import BaseModel
sys.path.append(str(Path(__file__).resolve().parents[1]))
from client import Client
from fastapi_cache.fake_db import FAKE_DB
from fastapi_cache.config import Settings

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
    host = settings.redis_host
    port = settings.redis_port
    
    for attempt in range(10):
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

"""
getting stats from hit or miss cache 
"""
@app.get("/cache/stats")
def cache_stats(request: Request):
    stats = request.app.state.stats
    time.sleep(1)
    return stats

@app.delete("/cache/users/{user_id}")
def invalidate_user_cache(user_id: str, request: Request):
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