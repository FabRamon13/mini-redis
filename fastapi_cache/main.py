import json, sys, time, os, time, asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager 
from pydantic import BaseModel



sys.path.append(str(Path(__file__).resolve().parents[1]))

from client import Client
from fastapi_cache.fake_db import FAKE_DB

class UserUpdate(BaseModel):
    name:str
    role:str


@asynccontextmanager
async def lifespan(app: FastAPI):
    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "31337"))
    
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
    
    cache.set(cache_key, json.dumps(user), "EX", "30")
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
