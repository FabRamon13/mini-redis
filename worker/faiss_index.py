from ai.faiss_store import FaissVectorStore


_faiss_stores = {}
_faiss_fingerprints = {}


def build_signature(provider, model_id, model_revision, dimensions):
    return provider, model_id, model_revision, dimensions


def _compatible_entries(entries, provider, model_id, model_revision, dimensions):
    return [
        entry
        for entry in entries
        if entry.get("provider") == provider
        and entry.get("model_id") == model_id
        and entry.get("model_revision") == model_revision
        and entry.get("embedding_dimensions") == dimensions
    ]


def _build_fingerprint(entries):
    return tuple(sorted(entry["entry_id"] for entry in entries))


def rebuild_faiss_index(entries, provider, model_id, model_revision, dimensions):
    signature = build_signature(
        provider,
        model_id,
        model_revision,
        dimensions,
    )
    compatible_entries = _compatible_entries(
        entries,
        provider,
        model_id,
        model_revision,
        dimensions,
    )
    store = FaissVectorStore(dimensions)

    for entry in compatible_entries:
        try:
            store.add(entry)
        except ValueError:
            continue

    _faiss_stores[signature] = store
    _faiss_fingerprints[signature] = _build_fingerprint(compatible_entries)

    return store


def get_faiss_index(entries, provider, model_id, model_revision, dimensions):
    signature = build_signature(
        provider,
        model_id,
        model_revision,
        dimensions,
    )
    compatible_entries = _compatible_entries(
        entries,
        provider,
        model_id,
        model_revision,
        dimensions,
    )
    fingerprint = _build_fingerprint(compatible_entries)

    if (
        signature not in _faiss_stores
        or _faiss_fingerprints.get(signature) != fingerprint
    ):
        return rebuild_faiss_index(
            entries,
            provider,
            model_id,
            model_revision,
            dimensions,
        )

    return _faiss_stores[signature]


def rebuild_faiss_indexes(entries, provider=None):
    reset_faiss_indexes()
    signatures = {
        build_signature(
            entry["provider"],
            entry["model_id"],
            entry["model_revision"],
            entry["embedding_dimensions"],
        )
        for entry in entries
        if provider is None or entry.get("provider") == provider
    }

    for signature in signatures:
        rebuild_faiss_index(entries, *signature)

    return len(signatures)


def add_to_faiss(entry):
    signature = build_signature(
        entry["provider"],
        entry["model_id"],
        entry["model_revision"],
        entry["embedding_dimensions"],
    )
    store = _faiss_stores.get(signature)

    if store is None:
        return False

    entry_id = entry["entry_id"]

    if entry_id in _faiss_fingerprints[signature]:
        return False

    try:
        store.add(entry)
    except ValueError:
        return False

    _faiss_fingerprints[signature] = tuple(
        sorted((*_faiss_fingerprints[signature], entry_id))
    )

    return True


def reset_faiss_indexes():
    _faiss_stores.clear()
    _faiss_fingerprints.clear()
