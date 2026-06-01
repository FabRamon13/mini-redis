import hashlib
import math
import re 


def embed(text: str, dimensions: int = 64):
    """
    Convert text into a deterministic vector representation.

    This lightweight implementation is used to build and test the
    semantic-cache architecture before replacing it with a real embedding
    model such as Hugging Face sentence-transformers.
    """
    vector = [0.0] * dimensions

    for word in text.lower().split():
        digest = hashlib.sha256(
            word.encode("utf-8")
            ).digest()
        
        index = digest[0] % dimensions
        
        vector[index] += 1.0

    norm = math.sqrt(
        sum(x * x for x in vector))

    if norm == 0:
        return vector

    return [x / norm for x in vector]