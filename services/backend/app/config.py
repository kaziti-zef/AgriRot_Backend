import os

DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:8001")
CORE_SERVICE_URL = os.getenv("CORE_SERVICE_URL", "http://localhost:8002")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrorot.db")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-a-changer-en-production-32+")
APP_ENV = os.getenv("APP_ENV", "development")          # "production" active les vérifications de démarrage
SECRETS_FAIBLES = {"dev-secret-a-changer-en-production-32+", "changez-moi", "secret", ""}


def verifier_secret(env: str | None = None, secret: str | None = None) -> str | None:
    """Renvoie un message d'erreur si le secret JWT est inacceptable, None sinon."""
    env = env or APP_ENV
    secret = JWT_SECRET if secret is None else secret
    faible = secret in SECRETS_FAIBLES or len(secret) < 32
    if faible and env == "production":
        return ("JWT_SECRET absent, par défaut ou trop court (32 caractères minimum). Générez-en un : "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    return None
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", 60))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", 7))
COMPUTATION_TTL_HOURS = int(os.getenv("COMPUTATION_TTL_HOURS", 24))
MONITORING_INTERVAL_HOURS = float(os.getenv("MONITORING_INTERVAL_HOURS", 24))   # 0 = pas de surveillance automatique
INVITATION_DAYS = 7
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://agrorot.example")
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o]
DISCLAIMER = ("Outil d'aide à la décision : ces estimations soutiennent votre jugement et ne remplacent pas "
              "l'avis d'un agronome local.")
