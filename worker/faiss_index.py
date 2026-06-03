from ai.faiss_store import FaissVectorStore


_faiss_stores = {}
_faiss_fingerprints = {}


def build_signature(provider, model_id, model_revision, dimensions):
    return (provider, model_id, model_revision, dimensions)


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
    entry_ids = []

    for entry in entries:
        entry_id = entry.get("entry_id")

        if isinstance(entry_id, str) and entry_id:
            entry_ids.append(entry_id)

    return tuple(sorted(entry_ids))


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

    signatures = set()

    for entry in entries:
        if provider is not None and entry.get("provider") != provider:
            continue

        entry_provider = entry.get("provider")
        model_id = entry.get("model_id")
        model_revision = entry.get("model_revision")
        dimensions = entry.get("embedding_dimensions")

        if (
            not entry_provider
            or not model_id
            or not model_revision
            or isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or dimensions <= 0
        ):
            continue

        signatures.add(
            build_signature(
                entry_provider,
                model_id,
                model_revision,
                dimensions,
            )
        )

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

def get_faiss_index_size(provider=None, model_id=None, model_revision=None, dimensions=None):
    if provider is None:
        return sum(store.index.ntotal for store in _faiss_stores.values())

    signature = build_signature(provider, model_id, model_revision, dimensions)
    store = _faiss_stores.get(signature)

    if store is None:
        return 0

    return store.index.ntotal


def reset_faiss_indexes():
    _faiss_stores.clear()
    _faiss_fingerprints.clear()
