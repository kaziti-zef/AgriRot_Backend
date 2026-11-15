"""T45 - Classement -> poids par la méthode ROC (Rank Order Centroid).

w_i = (1/n) x somme_{k=i..n} 1/k. Pour 6 priorités : 0,41 ; 0,24 ; 0,16 ; 0,10 ; 0,06 ; 0,03,
exactement les poids de l'exemple du contrat (§9)."""
KEYS = ["water_saving", "income", "soil_health", "nitrogen", "erosion_control", "fodder"]
DEFAULT = {k: round(1 / len(KEYS), 4) for k in KEYS}


def roc(n: int) -> list[float]:
    return [sum(1 / k for k in range(i, n + 1)) / n for i in range(1, n + 1)]


def ranking_to_weights(ranking: list[str]) -> dict[str, float]:
    """Les priorités non classées reçoivent 0 ; les poids classés suivent ROC sur le nombre de priorités."""
    w = dict.fromkeys(KEYS, 0.0)
    for k, v in zip(ranking, roc(len(KEYS))):
        w[k] = v
    s = sum(w.values())
    return {k: round(v / s, 2) for k, v in w.items()}


def normaliser(weights: dict[str, float]) -> dict[str, float]:
    w = {k: max(0.0, float(weights.get(k, 0.0))) for k in KEYS}
    s = sum(w.values())
    if s <= 0:
        return dict(DEFAULT)
    return {k: round(v / s, 2) for k, v in w.items()}
