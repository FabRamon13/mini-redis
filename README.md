# Mini Redis Clone

A Redis-inspired TCP key-value store built in Python using sockets and a custom RESP-style protocol parser.

This project was built to understand how backend systems and networked databases work internally, including:

- TCP networking
- request parsing
- serialization
- persistence
- expiration logic
- concurrent clients
- containerized backend architecture

The project later evolved into a Dockerized FastAPI caching layer using the Redis clone as backend infrastructure.

---

## Features

## Core Redis Features

- TCP client/server architecture
- RESP-style protocol parser and serializer
- Command dispatch layer
- In-memory key-value storage
- PING / GET / SET / DELETE / FLUSH
- MGET / MSET
- EXISTS / TTL
- TTL expiration with lazy cleanup
- Append-only file (AOF) persistence
- Concurrent client handling with gevent
- Thread-safe shared state using locks

## FastAPI Cache Integration

- FastAPI cache-aside architecture
- Dockerized multi-service deployment
- Cache hit/miss tracking
- Cache invalidation endpoints
- Request timing metrics
- Simulated database latency

---

## System Architecture

```text
Browser / Client
↓
FastAPI API Container
↓
Redis Clone TCP Cache
↓
In-Memory Store
↓
AOF Persistence Layer
↓
Fake Database
```

---

## Request Lifecycle

1. Client serializes commands into RESP-style byte streams
2. TCP socket sends bytes to the server
3. Server parses bytes into Python objects
4. Command dispatcher executes the appropriate method
5. Server serializes the response
6. Client parses the response back into Python values

---

## Example Commands

```python
client.set("name", "Ramon")
client.get("name")

client.set("temp", "123", "EX", "10")
client.ttl("temp")

client.mset("k1", "v1", "k2", "v2")
client.mget("k1", "k2")
```

---


## TTL Expiration

TTL support was implemented using lazy expiration.

Expiration timestamps are stored separately from values:

- `_kv` stores key/value pairs
- `_expiry` stores expiration timestamps

Expired keys are removed when accessed.

---

## Persistence

The server uses an append-only file (AOF) persistence model.

Write operations are serialized using the RESP protocol and replayed on server startup to rebuild in-memory state.

This introduces concepts similar to:

- Write-ahead logging
- Event sourcing
- Redis AOF persistence

---

# Dockerized Deployment

Run the full system:

```bash
docker compose up --build
```

Services:

- FastAPI API container
- Redis clone container

FastAPI runs on:

```text
http://127.0.0.1:8000
```

---

# Tests

Integration tests cover:

- SET / GET
- overwrite behavior
- missing keys
- MSET / MGET
- TTL expiration
- AOF persistence
- concurrent clients

---

# Observability & Infrastructure

The FastAPI layer includes operational tooling commonly found in production backend services.

## Health Checks
### Endpoint

GET /health

Returns service readiness information for:

- FastAPI API status
- Redis clone connectivity

## Request Tracing

Every request receives a unique request ID:

X-Request-ID

Request metadata is logged with:

- request ID
- endpoint path
- status code
- latency
- client IP

## Configuration Management

Application configuration is centralized using typed settings loaded from environment variables.

Examples:

- redis_host
- redis_port
- cache_ttl

This enables environment-specific configuration for local development, Docker deployments, and future cloud environments.

---

# Benchmarking

The project includes benchmarking utilities for measuring cache effectiveness and request latency.

## Cache Performance

Example benchmark results:

Cache Miss Latency: 1023.86 ms
Cache Hit Latency: 5.96 ms
Latency Improvement: 99.42%

This demonstrates the effectiveness of the cache-aside architecture for repeated requests.

Metrics collected:

- p50 latency
- p95 latency
- average latency
- cache hit improvement

---

# Docker Persistence

Append-only file persistence is stored in a Docker volume:

redis_data:/app/data

This allows cached state and persistence logs to survive container restarts and container recreation.

--- 

# Graceful Shutdown

The FastAPI application manages cache client lifecycle using lifespan events:

Startup
→ Create shared cache connection

Shutdown
→ Close socket connection cleanly

This prevents resource leaks and prepares the system for future worker and queue infrastructure.

---

# Distributed Worker Queue

This project includes a queue-backed async processing system.


FastAPI API
↓
LPUSH job_id
↓
Redis Clone Queue
↓
RPOP by Worker Pool
↓
Job Status Store

--- 

## Architecture:

# Current Limitations

- No active background expiration sweeps
- No AOF compaction/rewrite
- No replication or clustering
- No snapshotting
- TTL replay after restart resets expiration duration
- Limited RESP compatibility compared to real Redis
- No distributed worker queue
- No semantic cache layer
- No metrics dashboard


