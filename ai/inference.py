from providers.fake_provider import generate as fake_generate

def generate_response(prompt, provider = "fake"):
    if provider == "fake":
        return fake_generate(prompt)
    if provider == "huggingface":
        from providers.huggingface_provider import generate as hf_generate
        return hf_generate(prompt)
    
    raise ValueError(f"Unknown inference provider: {provider}")


