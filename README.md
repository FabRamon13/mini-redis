# Mini Redis Clone

A Redis-inspired TCP key-value store built in Python using sockets and a custom RESP-style protocol parser.

This project was built to understand how backend systems and networked databases work internally, including request parsing, serialization, persistence, expiration logic, and client/server communication.

## Features

- TCP client/server architecture
- RESP-style protocol parser and serializer
- Command dispatch layer
- In-memory key-value storage
- PING / GET / SET / DELETE / FLUSH
- MGET / MSET
- EXISTS / TTL
- TTL expiration with lazy cleanup
- Append-only file persistence
- Concurrent client handling with gevent
- Thread-safe write/read operations using locks
- Integration tests for core commands, TTL, persistence, and concurrency


## Architecture

Client
↓
RESP Serialization
↓
TCP Socket
↓
Server
↓
Command Dispatch
↓
In-memory Key-Value Store
↓
Persistence Layer

## Request Lifecycle

1. Client serializes commands into RESP-style byte streams
2. TCP socket sends bytes to the server
3. Server parses bytes into Python objects
4. Command dispatcher executes the appropriate method
5. Server serializes the response
6. Client parses the response back into Python values

## Example Commands

```python
client.set("name", "Ramon")
client.get("name")

client.set("temp", "123", "EX", "10")
client.ttl("temp")

client.mset("k1", "v1", "k2", "v2")
client.mget("k1", "k2")


# TTL Notes

```md
## TTL Expiration

TTL support was implemented using lazy expiration.

Expiration timestamps are stored separately from values:

- `_kv` stores key/value pairs
- `_expiry` stores expiration timestamps

Expired keys are removed when accessed.

## Persistence

The server uses an append-only file (AOF) persistence model.

Write operations are appended to disk and replayed on server startup to rebuild in-memory state.

This introduces concepts similar to:

- Write-ahead logging
- Event sourcing
- Redis AOF persistence

## Current Limitations

- Persistence format is simplified and space-delimited
- No AOF compaction/rewrite
- No background expiration sweeps
- Nested values are not safely persisted
- No authentication or replication

## Future Improvements

- EXISTS / TTL command expansion
- Active expiration sweeps
- Improved RESP-compliant persistence
- Async worker queue integration
- FastAPI cache integration
- Snapshotting and AOF compaction
- Docker deployment

