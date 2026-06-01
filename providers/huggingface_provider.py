from sentence_transformers import SentenceTransformer

_model = None

def get_model():
    global _model
    
    if _model is None:
        print("Loading HuggingFace model...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

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
        "embedding_dimensions": len(embedding),
        "message": "Embedding generated successfully."
    }



    
