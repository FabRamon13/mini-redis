# Mini Redis AI Infrastructure Platform

## Overview

Mini Redis AI Infrastructure Platform is a backend systems and AI infrastructure project built from first principles.

The project began as a Redis-inspired TCP key-value store written in Python and evolved into a distributed inference platform featuring durable job processing, semantic caching, vector search, observability, and automated testing.

The system demonstrates concepts commonly found in backend, platform, and AI infrastructure engineering:

* Custom TCP networking
* RESP protocol parsing
* Durable persistence
* Distributed job processing
* Lease-based worker coordination
* Semantic caching
* Vector search
* AI inference routing
* Observability and metrics
* CI/CD validation

---

# Architecture

```text
                 Client
                    │
                    ▼
              FastAPI API
                    │
                    ▼
          Redis Clone Datastore
      ┌─────────────┼─────────────┐
      │             │             │
      ▼             ▼             ▼
 Key/Value      Job Queue      Metrics
   Store          State         Store
                    │
                    ▼
                 Workers
                    │
                    ▼
             Provider Router
            ┌──────────────┐
            │              │
            ▼              ▼
      Fake Provider   Hugging Face
            │              │
            └──────┬───────┘
                   ▼
             Semantic Cache
                   │
                   ▼
              FAISS Index
```

---

# Core Features

## Redis Clone

* TCP client/server architecture
* RESP-style protocol parser
* Command dispatch layer
* Thread-safe shared state
* Concurrent client handling
* Key-value storage
* TTL expiration
* AOF persistence
* Startup replay
* Atomic counters

### Supported Commands

```text
GET
SET
DELETE
FLUSH

MGET
MSET

EXISTS
TTL

LPUSH
RPOP
LLEN
LRANGE
LREM

INCR
INCRBY

ENQUEUE
CLAIM
UPDATECLAIM
REQUEUE
ACK
FINISH
```

---

# Persistence

All mutating commands are written to an append-only file.

```text
SET
MSET
DELETE
LPUSH
CLAIM
FINISH
INCR
INCRBY
...
```

During startup:

```text
Server Starts
      ↓
Read AOF
      ↓
Replay Commands
      ↓
Rebuild State
```

Redis Clone remains the durable source of truth for:

* queue state
* semantic cache entries
* metrics
* job metadata

---

# Distributed Worker Queue

The project includes a durable queue architecture inspired by systems such as:

* Celery
* Sidekiq
* BullMQ

## Queue Lifecycle

```text
Queued
  │
  ▼
Claimed
  │
  ▼
Processing
  │
  ├────► Requeue
  │
  ├────► Complete
  │
  └────► Dead Letter
```

## Reliability Features

### Claim Tokens

Every claimed job receives a unique claim token.

```text
Job
 ↓
Claim
 ↓
Claim Token
```

Only the owning worker can:

* ACK
* REQUEUE
* FINISH
* UPDATECLAIM

### Worker Leases

Workers claim jobs using time-based leases.

```text
Claim
 ↓
Lease
 ↓
Heartbeat
 ↓
Lease Extension
```

### Recovery

Stale claims are automatically recovered.

```text
Worker Crash
 ↓
Lease Expiration
 ↓
Recovery Scan
 ↓
Requeue
```

This provides at-least-once delivery semantics.

---

# AI Infrastructure Layer

Inference requests are processed asynchronously by workers.

```text
POST /inference
       ↓
Queue
       ↓
Worker
       ↓
Provider Router
       ↓
Model Provider
       ↓
Response
```

Supported providers:

* Fake Provider
* Hugging Face Provider

Provider routing allows new providers to be added without modifying worker execution logic.

---

# Semantic Cache

The semantic cache reduces repeated inference costs.

Instead of matching exact strings:

```text
Prompt A == Prompt B
```

the cache compares vector similarity:

```text
Embedding A
      vs
Embedding B
```

## Semantic Cache Flow

```text
Prompt
   ↓
Embedding Generation
   ↓
Vector Search
   ↓
Similarity Threshold
   ↓
Hit / Miss
```

Each cache entry stores:

* prompt
* provider
* model_id
* model_revision
* embedding_dimensions
* embedding
* response

Provider and model isolation prevent cross-model cache contamination.

---

# FAISS Vector Search

The project supports two search engines:

## Linear Search

```text
O(n)
```

Every cached embedding is scanned.

## FAISS Search

```text
Approximate Nearest Neighbor Search
```

Substantially faster retrieval at larger scales.

### Signature Isolation

Separate FAISS indexes are maintained for:

```text
provider
model_id
model_revision
embedding_dimensions
```

This prevents incompatible embeddings from sharing indexes.

### Rebuild Strategy

Redis remains the source of truth.

FAISS is treated as an acceleration layer.

```text
Worker Startup
      ↓
Load Semantic Cache Entries
      ↓
Validate Signatures
      ↓
Rebuild FAISS Indexes
```

If FAISS indexes are lost, workers automatically rebuild them.

---

# Metrics & Observability

The platform exposes both JSON and Prometheus-style metrics.

## JSON Metrics

```http
GET /jobs/metrics
```

## Prometheus Metrics

```http
GET /metrics
```

Tracked metrics include:

```text
processed_jobs
failed_jobs

queued_jobs
processing_jobs
dead_jobs

semantic_cache_hits
semantic_cache_misses
semantic_cache_hit_rate

faiss_search_count
faiss_search_latency_ms_avg

linear_search_count
linear_search_latency_ms_avg

provider_call_count
provider_latency_ms_avg
```

---

# FastAPI API

## Health

```http
GET /health
```

## Inference

```http
POST /inference
```

## Job Status

```http
GET /jobs/{job_id}
```

## Metrics

```http
GET /jobs/metrics
GET /metrics
```

## Cache Invalidation

```http
DELETE /cache/users/{user_id}
```

---

# Configuration

Environment-driven configuration controls:

```text
REDIS_HOST
REDIS_PORT

SEMANTIC_CACHE_THRESHOLD

VECTOR_SEARCH_ENGINE

WORKER_LEASE_SECONDS

WORKER_RECOVERY_INTERVAL_SECONDS

SEMANTIC_CACHE_MAX_ENTRIES
```

---

# Testing

The project includes:

* unit tests
* integration tests
* persistence tests
* queue tests
* semantic cache tests
* FAISS rebuild tests
* API tests

Current status:

```text
162 tests passing
5 skipped
```

Validation pipeline:

```bash
python -m unittest discover -s tests -v
python -m compileall -q redis_clone worker fastapi_cache ai providers tests benchmarks
docker compose config
```

---

# CI/CD

GitHub Actions validates:

* dependency installation
* compile checks
* automated tests
* Docker Compose configuration

Every push and pull request runs the validation pipeline automatically.

---

# Running Locally

```bash
docker compose up --build
```

API:

```text
http://localhost:8000
```

Health Check:

```bash
curl http://localhost:8000/health
```

---

# Current Limitations

* Educational Redis implementation, not production Redis
* No authentication or TLS
* No AOF rewrite/compaction
* No replication
* No clustering
* No snapshot persistence
* At-least-once delivery semantics
* Semantic cache insertion is not fully atomic
* FAISS indexes are worker-local
* Docker Compose configuration is development-oriented

---

# Technology Stack

Backend:

* Python
* FastAPI
* gevent

AI:

* Hugging Face Transformers
* Sentence Transformers
* FAISS

Infrastructure:

* Docker
* Docker Compose
* GitHub Actions

Storage:

* Custom Redis-inspired datastore
* Append-only persistence

Testing:

* unittest
* integration testing
* benchmark tooling

```
```
