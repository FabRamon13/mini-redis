import math 

def cosine_similarity(a,b):
    dot = sum( x * y for x,y in zip(a,b))

    mag_a = math.sqrt(
        sum(x*x for x in a)
    )

    mag_b = math.sqrt(
        sum(x*x for x in b)
    )

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a / mag_b)