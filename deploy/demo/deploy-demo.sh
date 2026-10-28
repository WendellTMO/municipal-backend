#!/usr/bin/env bash
# Deploy manual da demo. Rode na VM, dentro do clone do backend, na branch demo.
# Faz o mesmo que o job deploy do ci.yml, sem passar pelo GitHub Actions.
set -euo pipefail

ENV_FILE="${ENV_FILE:-$HOME/buska-demo.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Falta $ENV_FILE. Modelo: deploy/demo/env.demo.example"
  exit 1
fi

cp "$ENV_FILE" .env.prod
chmod 600 .env.prod

# Carrega as variáveis só para o shell usar nos comandos abaixo
set -a
source .env.prod
set +a

export API_IMAGE="buska-backend:demo-$(git rev-parse --short HEAD)"
docker build -t "$API_IMAGE" .

docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d db
for i in $(seq 1 60); do
  if docker exec buska_db_prod pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
    break
  fi
  echo "Esperando o banco ($i/60)"
  sleep 2
done
docker exec buska_db_prod psql -U "$DB_USER" -d "$DB_NAME" \
  -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'

# Migrações rodam no host contra a porta publicada do banco, como no ci.yml
export DB_HOST=localhost DB_PORT=5432
uv sync --frozen
uv run alembic upgrade head

docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d api scheduler

for i in $(seq 1 30); do
  if curl -sf http://localhost:5000/health >/dev/null; then
    echo "API no ar"
    break
  fi
  echo "Esperando a API ($i/30)"
  sleep 5
done
curl -sf http://localhost:5000/swagger.json >/dev/null
docker logs buska_scheduler 2>&1 | grep "Scheduler up with"
rm -f .env.prod
echo "Deploy da demo concluído: $API_IMAGE"
