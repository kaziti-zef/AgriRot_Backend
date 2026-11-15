up:        ; docker compose up --build
dev-core:  ; cd services/agrorot-core && uvicorn app.main:app --reload --port 8002
dev-data:  ; cd services/data-service && uvicorn app.main:app --reload --port 8001
dev-back:  ; cd services/backend && uvicorn app.main:app --reload --port 8000
test:      ; cd services/agrorot-core && pytest -q
