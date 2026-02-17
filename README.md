# LiveRoll Backend

API e worker do LiveRoll (FastAPI + PostgreSQL + Redis) para sorteios em tempo real com integração Twitch/YouTube.

## Stack
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Alembic
- PostgreSQL
- Redis
- Worker assíncrono (`app.workers.chat_worker`)

## Estrutura
```text
app/
  api/
  core/
  db/
  models/
  schemas/
  services/
  static/
  templates/
  workers/
alembic/
tests/
alembic.ini
requirements.txt
```

## Pré-requisitos
- Python 3.12+
- PostgreSQL
- Redis

## Configuração local
1. Crie e ative ambiente virtual.
2. Instale dependências:
```bash
pip install -r requirements.txt
```
3. Crie o arquivo de ambiente:
```bash
cp .env.example .env
```
4. Ajuste as variáveis no `.env` (DB, Redis, OAuth etc.).
5. Rode migrações:
```bash
alembic upgrade head
```
6. Suba a API:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
7. Em outro terminal, suba o worker:
```bash
python -m app.workers.chat_worker
```

## Endpoints importantes
- `GET /health`
- `GET /metrics`
- `GET /api/v1/public/links`
- `GET /api/v1/session`
- `GET /api/v1/giveaways`

## Testes
```bash
python -m pytest -q tests
```

## Segurança
- Tokens OAuth criptografados em repouso.
- CSRF em formulários.
- Isolamento por usuário nos sorteios.
- Rate limit básico em endpoints de controle.

## Observações
- Não versione `.env`.
- Use apenas placeholders no `.env.example`.
- Se credenciais forem expostas, revogue e gere novas.
