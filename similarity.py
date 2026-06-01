import math 

def cosine_similarity(a,b):
    if not a or not b:
        return 0.0

    if len(a) != len(b):
        return 0.0

    try:
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(y * y for y in b) ** 0.5
    except TypeError:
        return 0.0

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)