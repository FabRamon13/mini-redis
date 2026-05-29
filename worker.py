import json
import time
import os
import socket 

from client import Client
from datetime import datetime, timezone

def increment_metric(client,key):
    current = client.get(key)

    if current is None:
        client.set(key,"1")
    else:
        count = int(current.decode("utf-8"))
        client.set(key,str(count+1))

def main():
    client = connect_with_retry()

    print("Worker started. Waiting for jobs...")

    worker_id = socket.gethostname()
    print(f"Worker {worker_id} started. Waiting for jobs..", flush =True)

    while True:
        job_id = client.rpop("jobs")

        if job_id is None:
            time.sleep(1)
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
            time.sleep(3)

            job["status"] = "completed"
            job["completed_at"] = now_iso()
            job["failed_at"] = None
            job["error"] = None
            job["result"] = {
                "message": "Job completed successfully"
            }

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
        except ConnectionRefusedError:
            print(f"Redis not ready, retrying... attempt {attempt + 1}/{max_attempts}")
            time.sleep(delay)

    raise RuntimeError("Could not connect to Redis clone")

if __name__ == "__main__":
    main()