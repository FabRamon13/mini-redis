from sentence_transformers import SentenceTransformer
from observability.logging import configure_json_logger, log_event

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "main"

_model = None
logger = configure_json_logger("huggingface_provider")

def get_model():
    global _model
    
    if _model is None:
        log_event(
            logger,
            "model_loading",
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
        )
        _model = SentenceTransformer(
            MODEL_ID,
            revision = MODEL_REVISION,
        )
        log_event(
            logger,
            "model_loaded",
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
        )

    return _model

def get_model_metadata():
    return {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
    }

def embed_text(text):
    model = get_model()
    embedding = model.encode(text)

    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()

    return embedding

def generate(prompt):
    embedding = embed_text(prompt)

    return {
        "provider": "huggingface",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "embedding_dimensions": len(embedding),
        "message": "Embedding generated successfully."
    }

def get_model_id(provider):
    if provider == "huggingface":
        return MODEL_ID
    if provider == "fake":
        return "hash-embedding-v1"

    return "unknown"

def get_model_revision(provider):
    if provider == "huggingface":
        return MODEL_REVISION

    if provider == "fake":
        return "v1"

    return "unknown"



    
