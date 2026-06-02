# Mini Redis Clone

A Redis-inspired TCP key-value store built in Python using sockets and a custom RESP-style protocol parser.

This project was originally built to understand how backend systems and networked databases work internally, including:

* TCP networking
* Request parsing
* Serialization
* Persistence
* Expiration logic
* Concurrent clients
* Containerized backend architecture

The project later evolved into a distributed backend platform featuring:

* FastAPI cache-aside architecture
* Distributed worker queues
* Semantic caching
* AI inference routing
* Hugging Face model integration
* Observability and benchmarking

---

## Features

### Core Redis Features

* TCP client/server architecture
* RESP-style protocol parser and serializer
* Command dispatch layer
* In-memory key-value storage
* PING / GET / SET / DELETE / FLUSH
* MGET / MSET
* EXISTS / TTL
* TTL expiration with lazy cleanup
* Append-only file (AOF) persistence
* Concurrent client handling with gevent
* Thread-safe shared state using locks

### FastAPI Cache Integration

* FastAPI cache-aside architecture
* Dockerized multi-service deployment
* Cache hit/miss tracking
* Cache invalidation endpoints
* Request timing metrics
* Simulated database latency

### Distributed Worker Queue

* Asynchronous job processing
* Worker pool architecture
* Retry handling
* Dead-letter queue support
* Job status tracking
* Queue metrics
* Worker identification
* Scalable background processing

### AI Infrastructure Layer

* Inference job routing
* Provider abstraction layer
* Semantic cache
* Embedding generation
* Cosine similarity search
* Hugging Face integration
* Provider-safe caching
* AI workload benchmarking

---

## System Architecture

```text
Client
↓
FastAPI API
↓
Redis Clone
├── Key-Value Store
├── Persistence Layer
├── Job Queue
└── Metrics Store
↓
Worker Pool
↓
Provider Router
├── Fake Provider
└── Hugging Face Provider
↓
Semantic Cache
↓
Inference Results
```

---

## Request Lifecycle

### Redis Operations

1. Client serializes commands into RESP-style byte streams
2. TCP socket sends bytes to the server
3. Server parses bytes into Python objects
4. Command dispatcher executes the appropriate method
5. Server serializes the response
6. Client parses the response back into Python values

### Inference Operations

1. Client submits an inference request
2. FastAPI creates a job
3. Job is pushed into the Redis queue
4. Worker pulls the job
5. Semantic cache is checked
6. Cache hit returns immediately
7. Cache miss routes to a model provider
8. Response is stored and returned

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

Expiration timestamps are stored separately from values.

### Internal Storage

```python
_kv
_expiry
```

* `_kv` stores key/value pairs
* `_expiry` stores expiration timestamps

Expired keys are removed when accessed.

---

## Persistence

The server uses an append-only file (AOF) persistence model.

Write operations are serialized using the RESP protocol and replayed on server startup to rebuild in-memory state.

This introduces concepts similar to:

* Write-ahead logging
* Event sourcing
* Redis AOF persistence

---

## Dockerized Deployment

Run the full system:

```bash
docker compose up --build
```

### Services

* FastAPI API
* Redis Clone
* Worker Pool

FastAPI runs on:

```text
http://127.0.0.1:8000
```

---

## Distributed Worker Queue

The project includes a queue-backed asynchronous processing system inspired by production task queues such as:

* Celery
* Sidekiq
* BullMQ

### Queue Architecture

```text
FastAPI API
↓
LPUSH job_id
↓
Redis Clone Queue
↓
RPOP by Worker Pool
↓
Job Status Store
```

### Job Lifecycle

```text
Queued
↓
Running
↓
Completed
```

Failure path:

```text
Queued
↓
Running
↓
Retry
↓
Retry
↓
Failed
↓
Dead Letter Queue
```

### Job Metadata

Each job tracks:

* Status
* Attempts
* Max attempts
* Created time
* Start time
* Completion time
* Failure time
* Worker ID
* Result
* Error message

---

## AI Infrastructure Layer

The project evolved beyond a Redis clone into a lightweight AI serving platform.

Inference requests are submitted through FastAPI and executed asynchronously by workers.

### Inference Architecture

```text
Client
↓
POST /inference
↓
Job Queue
↓
Worker Pool
↓
Provider Router
↓
Model Provider
↓
Result Storage
```

### Supported Providers

* Fake Provider
* Hugging Face Provider

Provider routing allows new model providers to be added without modifying worker logic.

```text
generate_response()
├── fake
└── huggingface
```

---

## Semantic Cache

A semantic cache layer reduces repeated inference cost by matching requests based on embedding similarity rather than exact string equality.

### Flow

```text
Prompt
↓
Embedding Generation
↓
Cosine Similarity Search
↓
Cache Hit / Cache Miss
```

### Cache Storage

Each cache entry stores:

* Prompt
* Provider
* Embedding
* Response

### Provider-Safe Caching

Cache entries are isolated by provider.

Example:

```text
provider=fake
```

does not satisfy:

```text
provider=huggingface
```

even when prompts are identical.

### Metrics

Tracked metrics include:

* Semantic cache hits
* Semantic cache misses
* Semantic cache hit rate

Example:

```text
Hits: 9
Misses: 1
Hit Rate: 90%
```

---

## Hugging Face Integration

The worker supports real model execution through a provider abstraction layer.

### Current Model

```text
sentence-transformers/all-MiniLM-L6-v2
```

### Model Characteristics

* CPU-only deployment
* 384-dimensional embeddings
* Lazy-loaded model initialization
* Provider-based execution

The model is loaded only when required:

```text
Worker
↓
Hugging Face Provider
↓
Model Load
↓
Embedding Generation
```

---

## Observability & Infrastructure

The FastAPI layer includes operational tooling commonly found in production backend services.

### Health Checks

Endpoint:

```http
GET /health
```

Returns:

* API status
* Redis connectivity

### Request Tracing

Every request receives a unique request ID.

Headers:

```text
X-Request-ID
```

Logged metadata:

* Request ID
* Endpoint
* Status code
* Latency
* Client IP

### Configuration Management

Typed settings loaded from environment variables.

Examples:

* redis_host
* redis_port
* cache_ttl
* max_queue_size

---

## Benchmarking

The project includes benchmarking utilities for measuring cache effectiveness and inference latency.

### Semantic Cache Benchmark

Example results:

```text
Requests: 10
Hits: 9
Misses: 1

Hit Rate: 90%

p50 Latency: 66.71 ms
p95 Latency: 67.79 ms
Average Latency: 355.56 ms
```

### Latency Comparison

Cache miss:

```text
~3500 ms
```

Cache hit:

```text
~5–70 ms
```

This demonstrates the effectiveness of semantic caching for repeated inference requests.

---

## Tests

Integration tests cover:

* SET / GET
* Overwrite behavior
* Missing keys
* MSET / MGET
* TTL expiration
* AOF persistence
* Concurrent clients
* Queue operations
* Job lifecycle management
* Semantic cache functionality

---

## Docker Persistence

Append-only file persistence is stored inside a Docker volume.

```text
redis_data:/app/data
```

This allows persistence data to survive:

* Container restarts
* Container recreation
* Worker restarts

---

## Graceful Shutdown

The FastAPI application manages cache lifecycle using lifespan events.

### Startup

```text
Create shared cache connection
```

### Shutdown

```text
Close socket connection cleanly
```

This prevents resource leaks and prepares the system for future distributed deployments.

---

## Current Limitations

* No active background expiration sweeps
* No AOF compaction/rewrite
* No replication or clustering
* No snapshotting
* TTL replay after restart resets expiration duration
* Limited RESP compatibility compared to real Redis
* No distributed scheduling
* No vector database backend
* Semantic cache uses linear similarity search
* No model observability dashboard
* No Kubernetes deployment
* No multi-node worker orchestration

---

## Future Improvements

### Backend Infrastructure

* Redis replication
* Snapshot persistence
* AOF rewrite support
* Background expiration sweeps
* Cluster support

### AI Infrastructure

* OpenAI provider
* Additional Hugging Face providers
* Vector database integration
* RAG pipelines
* Model observability
* Request batching
* Streaming responses

### Cloud Infrastructure

* AWS deployment
* Kubernetes orchestration
* Terraform infrastructure
* CI/CD pipelines
* Distributed worker scaling
* Monitoring dashboards

---

## FAISS Boundary

Redis Clone remains the source of truth.

Redis stores:

- prompt
- provider
- model_id
- model_revision
- embedding_dimensions
- embedding
- response
- semantic cache metadata
- job state
- queue state

FAISS stores:

- vectors for nearest-neighbor search
- integer index IDs mapped to semantic cache entries

FAISS does not own durable state.

If the FAISS index is lost, corrupted, or restarted, it should be rebuilt from Redis semantic cache entries.

### Rebuild Flow

```text
Worker starts
↓
Read semantic_cache:index from Redis Clone
↓
Load semantic_cache:<uuid> entries
↓
Validate provider/model/dimensions
↓
Insert embeddings into FAISS
↓
Build faiss_id → entry_id mapping

```
```


