from embeddings import embed as fake_embed

def get_embedding(text, provider = "fake"):
    if provider == "fake":
        return fake_embed(text)

    if provider == "huggingface":
        from providers.huggingface_provider import embed_text
        return embed_text(text)

    raise ValueError(f"Unknown embedding provider: {provider}")