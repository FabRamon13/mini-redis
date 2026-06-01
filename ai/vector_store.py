from ai.similarity import cosine_similarity
class VectorStore:
    def __init__(self):
        self._entries =[]

    def add(self, prompt, embedding, response):
        self._entries.append({
            "prompt": prompt,
            "embedding": embedding,
            "response": response
        })

    def all(self):
        return self._entries
    
    def find_similar(self, embedding, threshold=0.75):
        best_match = None
        best_score = 0.0

        for entry in self._entries:
            score = cosine_similarity(
                embedding,
                entry["embedding"]
            )

            if score > best_score:
                best_score = score 
                best_match = entry
        
        if best_match is not None and best_score >= threshold:
            return best_match, best_score
        
        return None, best_score