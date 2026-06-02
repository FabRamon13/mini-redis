import json
import math
import uuid
from datetime import datetime, timezone
import heapq


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_model_id(provider):
    if provider == "huggingface":
        return "sentence-transformers/all-MiniLM-L6-v2"

    if provider == "fake":
        return "hash-embedding-v1"

    return "unknown"


def get_model_revision(provider):
    if provider == "huggingface":
        return "main"

    if provider == "fake":
        return "v1"

    return "unknown"


def is_valid_embedding(embedding):
    if not isinstance(embedding, list) or not embedding:
        return False
    return all(
        isinstance(value, (int, float)) 
        and not isinstance(value, bool)
        and math.isfinite(value)
        for value in embedding
    )


def is_valid_semantic_entry(entry):
    if not isinstance(entry, dict):
        return False

    required_fields = {
        "entry_id",
        "prompt",
        "provider",
        "model_id",
        "model_revision",
        "embedding",
        "response",
        "embedding_dimensions",
        "created_at",
    }
    if not required_fields.issubset(entry):
        return False

    embedding = entry["embedding"]

    return (
        isinstance(entry["entry_id"], str)
        and bool(entry["entry_id"])
        and isinstance(entry["prompt"], str)
        and bool(entry["prompt"])
        and isinstance(entry["provider"], str)
        and bool(entry["provider"])
        and isinstance(entry["model_id"], str)
        and bool(entry["model_id"])
        and isinstance(entry["model_revision"], str)
        and bool(entry["model_revision"])
        and isinstance(entry["created_at"], str)
        and isinstance(entry["embedding_dimensions"], int)
        and not isinstance(entry["embedding_dimensions"], bool)
        and is_valid_embedding(embedding)
        and entry["embedding_dimensions"] == len(embedding)
    )


def get_semantic_cache_entries(client):
    keys = client.lrange("semantic_cache:index", 0, -1)

    if not keys:
        return []

    entries = []

    for key in keys:
        try:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
        except UnicodeDecodeError:
            continue
        raw = client.get(key)

        if raw is None:
            continue
        
        try:
            entry = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        if not is_valid_semantic_entry(entry):
            continue

        entries.append(entry)

    return entries


def is_duplicate_semantic_entry(
    existing_entry,
    prompt,
    provider,
    model_id,
    model_revision,
):
    return (
        existing_entry.get("prompt") == prompt
        and existing_entry.get("provider") == provider
        and existing_entry.get("model_id") == model_id
        and existing_entry.get("model_revision") == model_revision
    )


def prune_semantic_cache(client, max_entries):
    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")

    keys = client.lrange("semantic_cache:index", 0, -1)

    if not keys or len(keys) <= max_entries:
        return 0

    removed = 0

    for key in keys[max_entries:]:
        if isinstance(key, bytes):
            try:
                key = key.decode("utf-8")
            except UnicodeDecodeError:
                continue

        client.delete(key)
        client.lrem("semantic_cache:index", key)
        removed += 1

    return removed


def save_semantic_cache_entry(
    client,
    prompt,
    embedding,
    response,
    provider,
    max_entries=1000,
):
    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")

    model_id = get_model_id(provider)
    model_revision = get_model_revision(provider)
    entries = get_semantic_cache_entries(client)

    for entry in entries:
        if is_duplicate_semantic_entry(
            entry,
            prompt,
            provider,
            model_id,
            model_revision,
        ):
            prune_semantic_cache(client, max_entries)
            return entry

    cache_id = str(uuid.uuid4())
    cache_key = f"semantic_cache:{cache_id}"
    entry = {
        "entry_id": cache_id,
        "prompt": prompt,
        "provider": provider,
        "model_id": model_id,
        "model_revision": model_revision,
        "embedding": embedding,
        "response": response,
        "embedding_dimensions": len(embedding),
        "created_at": now_iso(),
    }

    if not is_valid_semantic_entry(entry):
        raise ValueError("Invalid semantic cache entry")

    try:
        payload = json.dumps(entry)
    except (TypeError, ValueError) as exc:
        raise ValueError("Failed to serialize semantic cache entry") from exc

    client.set(cache_key, payload)
    client.lpush("semantic_cache:index", cache_key)
    prune_semantic_cache(client, max_entries)

    return entry
