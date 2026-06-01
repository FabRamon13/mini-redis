import json
import time
import os
import socket 

from client import Client
from datetime import datetime, timezone
from embedding_router import get_embedding 
from vector_store import VectorStore
from similarity import cosine_similarity
from inference import generate_response
from exceptions import Disconnect

vector_store = VectorStore()

def increment_metric(client,key):
    current = client.get(key)

    if current is None:
        client.set(key,"1")
    else:
        count = int(current.decode("utf-8"))
        client.set(key,str(count+1))

def process_demo_task(job):
    time.sleep(3)

    return {
        "message": "Job completed successfully"
    }

def get_semantic_cache_entries(client):
    index_raw = client.get("semantic_cache:index")

    if index_raw is None:
        return []

    keys = json.loads(index_raw.decode("utf-8"))
    entries = []

    for key in keys:
        raw = client.get(key)

        if raw is None:
            continue

        entry = json.loads(raw.decode("utf-8"))

        if not isinstance(entry, dict):
            continue

        if not entry.get("prompt"):
            continue

        if not entry.get("embedding"):
            continue

        if not entry.get("response"):
            continue

        entries.append(entry)

    return entries

def save_semantic_cache_entry(client, prompt, embedding, response,provider):
    cache_id = str(len(get_semantic_cache_entries(client)) + 1)
    cache_key = f"semantic_cache:{cache_id}"

    entry = {
        "prompt": prompt,
        "provider": provider,
        "embedding": embedding,
        "response": response,
    }

    client.set(cache_key, json.dumps(entry))

    index_raw = client.get("semantic_cache:index")

    if index_raw is None:
        keys = []
    else:
        keys = json.loads(index_raw.decode("utf-8"))

    keys.append(cache_key)

    client.set("semantic_cache:index", json.dumps(keys))

def process_inference(job,client):
    prompt = job["prompt"]
    provider = job.get("provider", "fake")
    vector = get_embedding(prompt, provider=provider)

    entries = get_semantic_cache_entries(client)

    best_match = None
    best_score = 0.0

    for entry in entries:
        if entry is None:
            continue

        if entry.get("provider", "fake") != provider:
            continue

        embedding = entry.get("embedding")

        if embedding is None:
            continue

        score = cosine_similarity(vector, embedding)

        if score > best_score:
            best_score = score
            best_match = entry

    if best_match is not None and best_score >= 0.75:
        increment_metric(client,"metrics:semantic_cache_hits")
        
        return {
            "prompt": prompt,
            "provider": provider,
            "cache": "hit",
            "matched_prompt": best_match["prompt"],
            "similarity_score": round(best_score, 4),
            "response": best_match["response"],
        }
    
    increment_metric(client, "metrics:semantic_cache_misses")

    ##only cache misses pay the expensie inference cost
    time.sleep(3)

    response = generate_response(prompt, provider = provider)

    save_semantic_cache_entry(client, prompt, vector, response,provider)
    
    return {
        "prompt": prompt,
        "provider": provider,
        "cache": "miss",
        "similarity_score": round(best_score, 4),
        "embedding_dimensions": len(vector),
        "response": response,
    }

def process_job(job,client):
    job_type = job["type"]

    if job_type == "demo_task":
        return process_demo_task(job)
    if job_type == "inference":
        return process_inference(job,client)

    raise ValueError(f"Unknown job type: {job_type}")

def main():
    client = connect_with_retry()

    worker_id = socket.gethostname()
    print(f"Worker {worker_id} started. Waiting for jobs..", flush =True)

    while True:
        try:
            job_id = client.rpop("jobs")

        except Disconnect:
            print("Lost redis connection, reconnecting", flush=True)
            client = connect_with_retry()
            continue
        
        except OSError:
            print("socket error, reconnecting", flush=True)
            client = connect_with_retry()
            continue

        if job_id is None:
            time.sleep(0.05)
            continue

        job_id = job_id.decode("utf-8")
        job_key = f"job:{job_id}"

        job_raw = client.get(job_key)

        if job_raw is None:
            continue

        job = json.loads(job_raw.decode("utf-8"))

        job["status"] = "running"
        job["started_at"] = now_iso()
        job["worker_id"] = worker_id
        client.set(job_key, json.dumps(job))

        print(f"Processing job {job_id}")

        try:            
            result = process_job(job, client)

            job["status"] = "completed"
            job["completed_at"] = now_iso()
            job["failed_at"] = None
            job["error"] = None
            job["result"] = result

            increment_metric(client, "metrics:processed_jobs")

        except Exception as exc:
            job["attempts"] +=1
            job["error"] = str(exc)

            if job["attempts"] < job["max_attempts"]:
                job["status"] = "queued"
                client.set(job_key,json.dumps(job))
                client.lpush("jobs", job_id)
                continue
            
            else:
                job["status"] = "failed"
                job["failed_at"] = now_iso()
                job["result"] = None
                job["error"] = str(exc)

                client.set(job_key,json.dumps(job))
                client.lpush("dead_jobs", job_id)
                increment_metric(client, "metrics:failed_jobs")
                continue

        client.set(job_key, json.dumps(job))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def connect_with_retry(max_attempts=10,delay=1):
    for attempt in range(max_attempts):
        try:
            return Client(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "31337")),
            )
        except (ConnectionRefusedError,OSError) as exc:
            print(f"Redis not ready, retrying... attempt {attempt + 1}/{max_attempts}: {exc}")
            time.sleep(delay)

    raise RuntimeError("Could not connect to Redis clone")

if __name__ == "__main__":
    main()