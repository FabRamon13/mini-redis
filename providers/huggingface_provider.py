from sentence_transformers import SentenceTransformer

_model = None

def get_model():
    global _model
    
    if _model is None:
        print("Loading HuggingFace model...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def generate(prompt):
    model = get_model()
    
    embedding = model.encode(prompt)

    return {
        "provider": "huggingface",
        "embedding_dimensions": len(embedding),
        "message": "Embedding generated successfully."
    }
