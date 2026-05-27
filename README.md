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

# Current Limitations

- No active background expiration sweeps
- No AOF compaction/rewrite
- No replication or clustering
- No snapshotting
- TTL replay after restart resets expiration duration
- Limited RESP compatibility compared to real Redis

---

# Future Improvements 

- Background expiration worker
- AOF rewrite/compaction
- Snapshot persistence
- Distributed worker queue
- Async task processing
- Metrics/observability dashboard
- Kubernetes deployment
- AI inference caching integration