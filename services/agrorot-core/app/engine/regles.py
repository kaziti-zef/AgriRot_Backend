"""Catalogue des règles citées dans les explications (« Règle R1 »...).
Les codes C* sont éliminatoires (niveau 1), les R* sont des bonus/pénalités (niveau 2)."""
CATALOGUE = [
    {"code": "C1", "niveau": 1, "nom": "Limites climatiques absolues"},
    {"code": "C2", "niveau": 1, "nom": "Cycle compatible avec la saison des pluies"},
    {"code": "C3", "niveau": 1, "nom": "Pas de chevauchement de cycles"},
    {"code": "C4", "niveau": 1, "nom": "Délai de retour respecté"},
    {"code": "C5", "niveau": 1, "nom": "Pas deux cultures de la même famille à la suite", "souple": True},
    {"code": "C6", "niveau": 1, "nom": "pH et drainage compatibles"},
    {"code": "C0", "niveau": 1, "nom": "Culture exclue par l'agriculteur"},
    {"code": "C7", "niveau": 1, "nom": "Pas de culture très sensible sur pression sanitaire critique", "souple": True},
    {"code": "R1", "niveau": 2, "nom": "Répétition d'une même famille botanique", "critere": "S5"},
    {"code": "R2", "niveau": 2, "nom": "Légumineuse avant une culture exigeante en azote", "critere": "S3"},
    {"code": "R3", "niveau": 2, "nom": "Deux cultures exigeantes en azote à la suite", "critere": "S3"},
    {"code": "R4", "niveau": 2, "nom": "Satisfaction en eau insuffisante", "critere": "S2"},
    {"code": "R5", "niveau": 2, "nom": "Sol nu pendant les pluies intenses", "critere": "S4"},
    {"code": "R6", "niveau": 2, "nom": "Accumulation de pression d'un bioagresseur du sol", "critere": "S5"},
    {"code": "R7", "niveau": 2, "nom": "Chaleur excessive pendant la floraison", "critere": "S1"},
    {"code": "R8", "niveau": 2, "nom": "Culture sans débouché déclaré", "critere": "S6"},
]
