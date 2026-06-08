import json
import math
import time
import os
import socket
import uuid
import threading
import logging


from redis_clone.client import Client
from datetime import datetime, timezone
from worker.semantic_cache import (
    get_model_id,
    get_model_revision,
    get_semantic_cache_entries,
    save_semantic_cache_entry,
)
from redis_clone.exceptions import Disconnect
from ai.vector_store import VectorStore
from ai.embedding_router import get_embedding
from ai.inference import generate_response
from worker.faiss_index import add_to_faiss
from worker.faiss_index import get_faiss_index
from worker.faiss_index import rebuild_faiss_indexes
from observability.logging import configure_json_logger, log_event


logger = configure_json_logger("worker")

def load_semantic_cache_threshold(value=None):
    if value is None:
        value = os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.75")

    try:
        threshold = float(value)
    except (TypeError, ValueError):
        raise ValueError("SEMANTIC_CACHE_THRESHOLD must be a number")

    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("SEMANTIC_CACHE_THRESHOLD must be between 0.0 and 1.0")

    return threshold

def load_non_negative_float(name, default):
    value = os.getenv(name, str(default))

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")

    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be a non-negative number")

    return parsed

def load_positive_int(name, default, value=None):
    if value is None:
        value = os.getenv(name, str(default))

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")

    if parsed <= 0:
        raise ValueError(f"{name} must be positive")

    return parsed

def load_vector_search_engine(value=None):
    if value is None:
        value = os.getenv("VECTOR_SEARCH_ENGINE", "faiss")

    engine = value.lower()

    if engine not in {"linear", "faiss"}:
        raise ValueError("VECTOR_SEARCH_ENGINE must be 'linear' or 'faiss'")

    return engine

DEMO_TASK_DELAY_SECONDS = load_non_negative_float("DEMO_TASK_DELAY_SECONDS", 0.0)
DEMO_INFERENCE_DELAY_SECONDS = load_non_negative_float("DEMO_INFERENCE_DELAY_SECONDS", 0.0)

WORKER_LEASE_SECONDS = load_positive_int("WORKER_LEASE_SECONDS", 60)
WORKER_RECOVERY_INTERVAL_SECONDS = load_positive_int("WORKER_RECOVERY_INTERVAL_SECONDS",30,)
WORKER_HEARTBEAT_INTERVAL_SECONDS = load_positive_int("WORKER_HEARTBEAT_INTERVAL_SECONDS", 15)

SEMANTIC_CACHE_THRESHOLD = load_semantic_cache_threshold()
SEMANTIC_CACHE_MAX_ENTRIES = load_positive_int("SEMANTIC_CACHE_MAX_ENTRIES", 1000)
VECTOR_SEARCH_ENGINE = load_vector_search_engine()


def increment_metric(client, key):
    return client.incr(key)

def increment_metric_by(client, key, amount):
    return client.incrby(key, int(amount))


def process_demo_task(job):
    time.sleep(DEMO_TASK_DELAY_SECONDS)

    return {
        "message": "Job completed successfully"
    }

def process_inference(job,client):
    job_id = job.get("id")
    request_id = job.get("request_id")
    prompt = job["prompt"]
    provider = job.get("provider", "fake")
    model_id = get_model_id(provider)
    model_revision = get_model_revision(provider)
    vector = get_embedding(prompt, provider=provider)

    entries = get_semantic_cache_entries(client)

    use_faiss = (
        provider == "huggingface"
        and VECTOR_SEARCH_ENGINE == "faiss"
    )
    search_engine = "faiss" if use_faiss else "linear"

    log_event(
        logger,
        "vector_search_started",
        request_id=request_id,
        job_id=job_id,
        provider=provider,
        search_engine=search_engine,
        candidate_count=len(entries),
    )

    if use_faiss:
        faiss_store = get_faiss_index(
            entries=entries,
            provider=provider,
            model_id=model_id,
            model_revision=model_revision,
            dimensions=len(vector),
        )

        search_start = time.perf_counter()

        top_matches = faiss_store.search_top_k(
            embedding=vector,
            k=3,
        )
        search_latency_ms = int((time.perf_counter() - search_start) * 1000)

        increment_metric(client, "metrics:faiss_search_count")
        increment_metric_by(client, "metrics:faiss_search_latency_ms_total", search_latency_ms)

    else:
        vector_store = VectorStore(entries)

        search_start = time.perf_counter()

        top_matches = vector_store.search_top_k(
            embedding=vector,
            provider=provider,
            model_id=model_id,
            model_revision=model_revision,
            k=3,
        )

        search_latency_ms = int((time.perf_counter() - search_start) * 1000)

        increment_metric(client, "metrics:linear_search_count")
        increment_metric_by(client, "metrics:linear_search_latency_ms_total", search_latency_ms)

    log_event(
        logger,
        "vector_search_completed",
        request_id=request_id,
        job_id=job_id,
        provider=provider,
        search_engine=search_engine,
        candidate_count=len(entries),
        result_count=len(top_matches),
        duration_ms=search_latency_ms,
    )

    formatted_top_matches = [
        {
            "entry_id": item["entry"].get("entry_id"),
            "prompt": item["entry"].get("prompt"),
            "provider": item["entry"].get("provider"),
            "model_id": item["entry"].get("model_id"),
            "model_revision": item["entry"].get("model_revision"),
            "similarity_score": round(item["similarity_score"], 4),
        }
        for item in top_matches
    ]

    best_match = top_matches[0] if top_matches else None
    best_score = best_match["similarity_score"] if best_match else 0.0

    if best_match is not None and best_score >= SEMANTIC_CACHE_THRESHOLD:
        increment_metric(client,"metrics:semantic_cache_hits")
        log_event(
            logger,
            "semantic_cache_hit",
            request_id=request_id,
            job_id=job_id,
            provider=provider,
            search_engine=search_engine,
            similarity_score=round(best_score, 4),
        )

        return {
            "prompt": prompt,
            "provider": provider,
            "cache": "hit",
            "matched_prompt": best_match["entry"]["prompt"],
            "similarity_score": round(best_score, 4),
            "top_matches": formatted_top_matches,
            "response": best_match["entry"]["response"],
        }
    
    increment_metric(client, "metrics:semantic_cache_misses")
    log_event(
        logger,
        "semantic_cache_miss",
        request_id=request_id,
        job_id=job_id,
        provider=provider,
        search_engine=search_engine,
        similarity_score=round(best_score, 4),
    )

    time.sleep(DEMO_INFERENCE_DELAY_SECONDS)

    provider_start = time.perf_counter()

    response = generate_response(prompt, provider = provider)

    provider_latency_ms = int((time.perf_counter() - provider_start) * 1000)

    increment_metric(client, "metrics:provider_call_count")
    increment_metric_by(client, "metrics:provider_latency_ms_total", provider_latency_ms)
    log_event(
        logger,
        "provider_call_completed",
        request_id=request_id,
        job_id=job_id,
        provider=provider,
        duration_ms=provider_latency_ms,
    )

    saved_entry = save_semantic_cache_entry(
        client,
        prompt,
        vector,
        response,
        provider,
        SEMANTIC_CACHE_MAX_ENTRIES,
    )

    if use_faiss:
        add_to_faiss(saved_entry)
    
    return {
        "prompt": prompt,
        "provider": provider,
        "cache": "miss",
        "similarity_score": round(best_score, 4),
        "top_matches": formatted_top_matches,
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

def process_claimed_job(client, job_id, worker_id, claim_token="", claimed_at=None):
    job_key = f"job:{job_id}"
    job_raw = client.get(job_key)

    if job_raw is None:
        client.ack("processing_jobs", job_id, claim_token)
        log_event(
            logger,
            "orphaned_job_removed",
            level=logging.WARNING,
            job_id=job_id,
            worker_id=worker_id,
        )
        return

    job = json.loads(job_raw.decode("utf-8"))
    request_id = job.get("request_id")
    job["status"] = "running"
    job["started_at"] = now_iso()
    job["claimed_at"] = claimed_at or now_iso()
    job["lease_seconds"] = WORKER_LEASE_SECONDS
    job["worker_id"] = worker_id
    job["claim_token"] = claim_token

    if not client.update_claim(job_id, job_key, json.dumps(job), claim_token):
        log_event(
            logger,
            "job_claim_rejected",
            level=logging.WARNING,
            request_id=request_id,
            job_id=job_id,
            worker_id=worker_id,
        )
        return

    stop_heartbeat=threading.Event()
    heartbeat_thread = start_claim_heartbeat(client,job,job_id,job_key,claim_token,stop_heartbeat)
    processing_start = time.perf_counter()
    log_event(
        logger,
        "job_started",
        request_id=request_id,
        job_id=job_id,
        worker_id=worker_id,
        job_type=job.get("type"),
        provider=job.get("provider"),
        attempt=job.get("attempts", 0) + 1,
    )

    try:
        result = process_job(job, client)

        job["status"] = "completed"
        job["completed_at"] = now_iso()
        job["failed_at"] = None
        job["error"] = None
        job["result"] = result

        finished = client.finish(
            "processing_jobs",
            "",
            job_id,
            job_key,
            json.dumps(job),
            claim_token,
        )

        if finished:
            increment_metric(client, "metrics:processed_jobs")
            log_event(
                logger,
                "job_finished",
                request_id=request_id,
                job_id=job_id,
                worker_id=worker_id,
                job_type=job.get("type"),
                provider=job.get("provider"),
                cache_status=(
                    result.get("cache")
                    if isinstance(result, dict)
                    else None
                ),
                duration_ms=round(
                    (time.perf_counter() - processing_start) * 1000,
                    2,
                ),
            )

    except Exception as exc:
        job["attempts"] +=1
        job["error"] = str(exc)

        if job["attempts"] < job["max_attempts"]:
            job["status"] = "queued"
            job["worker_id"] = None
            job["claim_token"] = None
            job["claimed_at"] = None
            job["started_at"] = None
            requeued = client.requeue(
                "processing_jobs",
                "jobs",
                job_id,
                job_key,
                json.dumps(job),
                claim_token,
            )
            if requeued:
                log_event(
                    logger,
                    "job_requeued",
                    level=logging.WARNING,
                    request_id=request_id,
                    job_id=job_id,
                    worker_id=worker_id,
                    job_type=job.get("type"),
                    provider=job.get("provider"),
                    attempt=job["attempts"],
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            return

        job["status"] = "failed"
        job["failed_at"] = now_iso()
        job["result"] = None

        finished = client.finish(
            "processing_jobs",
            "dead_jobs",
            job_id,
            job_key,
            json.dumps(job),
            claim_token,
        )

        if finished:
            increment_metric(client, "metrics:failed_jobs")
            log_event(
                logger,
                "job_failed",
                level=logging.ERROR,
                exc_info=(type(exc), exc, exc.__traceback__),
                request_id=request_id,
                job_id=job_id,
                worker_id=worker_id,
                job_type=job.get("type"),
                provider=job.get("provider"),
                attempt=job["attempts"],
                duration_ms=round(
                    (time.perf_counter() - processing_start) * 1000,
                    2,
                ),
                error_type=type(exc).__name__,
                error=str(exc),
            )
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)

def parse_iso(value):
    if not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None

    return parsed

def start_claim_heartbeat(client,job,job_id,job_key,claim_token,stop_event,interval_seconds=WORKER_HEARTBEAT_INTERVAL_SECONDS):
    def heartbeat_loop():
        while not stop_event.wait(interval_seconds):
            job["claimed_at"] = now_iso()
            updated = client.update_claim(
                job_id,
                job_key,
                json.dumps(job),
                claim_token,
            )

            if not updated:
                log_event(
                    logger,
                    "claim_heartbeat_failed",
                    level=logging.WARNING,
                    request_id=job.get("request_id"),
                    job_id=job_id,
                    worker_id=job.get("worker_id"),
                )
                break

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return thread

def recover_stale_processing_jobs(client, now=None):
    job_ids = client.lrange("processing_jobs", 0, -1)

    if not job_ids:
        return 0

    recovered = 0
    now = now or datetime.now(timezone.utc)

    for raw_job_id in job_ids:
        try:
            job_id = (
                raw_job_id.decode("utf-8")
                if isinstance(raw_job_id, bytes)
                else str(raw_job_id)
            )
        except UnicodeDecodeError:
            log_event(
                logger,
                "recovery_job_skipped",
                level=logging.WARNING,
                reason="invalid_utf8_job_id",
            )
            continue

        job_key = f"job:{job_id}"
        claim = _load_claim(client, job_id)
        claim_token = claim.get("claim_token", "")
        raw_job = client.get(job_key)

        if raw_job is None:
            client.lrem("processing_jobs", job_id)
            log_event(
                logger,
                "orphaned_job_removed",
                level=logging.WARNING,
                job_id=job_id,
            )
            continue

        try:
            job = json.loads(raw_job.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            log_event(
                logger,
                "recovery_job_skipped",
                level=logging.WARNING,
                job_id=job_id,
                reason="invalid_job_metadata",
            )
            continue

        if not isinstance(job, dict):
            log_event(
                logger,
                "recovery_job_skipped",
                level=logging.WARNING,
                job_id=job_id,
                reason="invalid_job_metadata",
            )
            continue

        claimed_at = parse_iso(claim.get("claimed_at") or job.get("claimed_at"))

        try:
            lease_seconds = load_positive_int(
                "lease_seconds",
                WORKER_LEASE_SECONDS,
                claim.get("lease_seconds", job.get("lease_seconds", WORKER_LEASE_SECONDS)),
            )
        except ValueError:
            log_event(
                logger,
                "recovery_job_skipped",
                level=logging.WARNING,
                request_id=job.get("request_id"),
                job_id=job_id,
                reason="invalid_lease",
            )
            continue

        if claimed_at is None:
            log_event(
                logger,
                "recovery_job_skipped",
                level=logging.WARNING,
                request_id=job.get("request_id"),
                job_id=job_id,
                reason="invalid_claim_timestamp",
            )
            continue

        if (now - claimed_at).total_seconds() <= lease_seconds:
            continue

        job["status"] = "queued"
        job["worker_id"] = None
        job["claim_token"] = None
        job["claimed_at"] = None
        job["started_at"] = None
        job["error"] = "Recovered from stale worker claim"

        removed = client.requeue(
            "processing_jobs",
            "jobs",
            job_id,
            job_key,
            json.dumps(job),
            claim_token,
        )

        if removed:
            recovered += 1
            log_event(
                logger,
                "stale_job_recovered",
                level=logging.WARNING,
                request_id=job.get("request_id"),
                job_id=job_id,
                previous_worker_id=claim.get("worker_id"),
                age_seconds=round((now - claimed_at).total_seconds(), 2),
                lease_seconds=lease_seconds,
            )

    return recovered

def _load_claim(client, job_id):
    raw_claim = client.get(f"worker_claim:{job_id}")

    if raw_claim is None:
        return {}

    try:
        claim = json.loads(raw_claim.decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    return claim if isinstance(claim, dict) else {}

def rebuild_worker_faiss_indexes(client):
    if VECTOR_SEARCH_ENGINE != "faiss":
        return 0

    entries = get_semantic_cache_entries(client)
    return rebuild_faiss_indexes(entries, provider="huggingface")

def main():
    client = connect_with_retry()

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    recovered = recover_stale_processing_jobs(client)
    faiss_indexes = rebuild_worker_faiss_indexes(client)
    last_recovery = time.monotonic()

    log_event(logger, "recovery_scan_completed", recovered_jobs=recovered)
    log_event(logger, "faiss_indexes_rebuilt", index_count=faiss_indexes)
    log_event(logger, "worker_started", worker_id=worker_id)

    while True:
        try:
            if time.monotonic() - last_recovery >= WORKER_RECOVERY_INTERVAL_SECONDS:
                recovered = recover_stale_processing_jobs(client)
                last_recovery = time.monotonic()

                if recovered:
                    log_event(
                        logger,
                        "recovery_scan_completed",
                        recovered_jobs=recovered,
                    )

            claimed_at = now_iso()
            claim_token = str(uuid.uuid4())
            job_id = client.claim(
                "jobs",
                "processing_jobs",
                worker_id,
                claim_token,
                claimed_at,
                WORKER_LEASE_SECONDS,
            )

        except Disconnect:
            log_event(
                logger,
                "redis_connection_lost",
                level=logging.WARNING,
                worker_id=worker_id,
                error_type="Disconnect",
            )
            client = connect_with_retry()
            recovered = recover_stale_processing_jobs(client)
            faiss_indexes = rebuild_worker_faiss_indexes(client)
            log_event(
                logger,
                "redis_connection_restored",
                worker_id=worker_id,
                recovered_jobs=recovered,
                faiss_index_count=faiss_indexes,
            )
            last_recovery = time.monotonic()
            continue
        
        except OSError as exc:
            log_event(
                logger,
                "redis_connection_lost",
                level=logging.WARNING,
                worker_id=worker_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            client = connect_with_retry()
            recovered = recover_stale_processing_jobs(client)
            faiss_indexes = rebuild_worker_faiss_indexes(client)
            log_event(
                logger,
                "redis_connection_restored",
                worker_id=worker_id,
                recovered_jobs=recovered,
                faiss_index_count=faiss_indexes,
            )
            last_recovery = time.monotonic()
            continue

        if job_id is None:
            time.sleep(0.05)
            continue

        job_id = job_id.decode("utf-8")
        log_event(
            logger,
            "job_claimed",
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=WORKER_LEASE_SECONDS,
        )
        process_claimed_job(client, job_id, worker_id, claim_token, claimed_at)

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
            log_event(
                logger,
                "redis_connection_retry",
                level=logging.WARNING,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            time.sleep(delay)

    raise RuntimeError("Could not connect to Redis clone")

if __name__ == "__main__":
    main()
