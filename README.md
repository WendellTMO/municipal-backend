# Buska Backend

API Flask para gerenciamento de rotas e viagens de transporte escolar.

## Setup Local

### Pré-requisitos
- Python 3.12+
- Docker + Docker Compose
- Ansible (para automação)

### Opção 1: Setup Automatizado (Recomendado)

```bash
# Clone o repositório e entre no diretório
git clone https://github.com/BusKa-org/buska-backend.git
cd buska-backend

# Setup completo (venv + dependências + banco + docker)
chmod +x setup.sh start.sh
./start.sh

# Para reinicializar o banco de dados
./start.sh -e clean_database=true
```

A API estará disponível em: **http://localhost:5000/docs**

---

### Opção 2: Setup Manual

```bash
# 1. Criar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependências
make install

# 3. Iniciar banco de dados (em outro terminal)
docker compose -f infra/database.yml up -d

# 4. Popular banco de dados
make initdb

# 5. Rodar servidor
make run
```

A API estará em: **http://localhost:5000** | Swagger: **http://localhost:5000/docs**

#### Verificar Instalação

```bash
# Verificar dependências
pip list | grep -E "python-json-logger"

# Verificar security headers
curl -I http://localhost:5000/v1/auth/login | grep -E "X-Content-Type|X-Frame|X-XSS|X-Request-ID"
```

---

## Comandos Disponíveis

### Desenvolvimento Local

```bash
make install        # Instalar dependências
make run            # Rodar servidor (porta 5000)
make initdb         # Criar e popular banco de dados
make deletedb       # Limpar banco de dados
make bdcon          # Conectar ao banco via psql
```

### Testes

```bash
make test               # Suíte completa
make test-unit          # Só testes unitários
make test-integration   # Só testes de integração (precisa do Postgres)
make db-test-create     # Criar o banco buska_test num volume já existente
```

Os testes de integração rodam contra o banco `buska_test`, separado do
`buska_db` de desenvolvimento. O `database/init.sql` cria os dois, e o Postgres
só executa esse script quando o volume é criado do zero. Se o seu volume é
anterior à criação do `buska_test`, os testes falham na conexão. Rode
`make db-test-create` para criar o banco que falta sem perder os dados de
desenvolvimento. O alvo é idempotente e pode ser rodado sempre.

### Docker (Produção)

```bash
make docker-build   # Buildar imagem
make docker-up      # Subir containers (porta 5000)
make docker-down    # Parar containers
make docker-logs    # Ver logs em tempo real
make docker-clean   # Limpar tudo (volumes + imagens)
```

## Convidar alunos por CSV

`scripts/convidar_csv.py` lê um CSV e cria os convites pela API (`POST /v1/convites/`, lotes de até 500). O e-mail com link e PIN sai pelo job de envio.

```bash
export BUSKA_API_URL=http://localhost:5000
export BUSKA_EMAIL=gestor@exemplo.test
export BUSKA_SENHA=...        # fica só no ambiente, nunca em arquivo
uv run python scripts/convidar_csv.py scripts/exemplo_convites.csv --dry-run   # só valida
uv run python scripts/convidar_csv.py scripts/exemplo_convites.csv             # cria os convites
```

Colunas: `nome` e `email` (obrigatórias), `telefone`, `ponto` (apelido ou id de um ponto da rota da linha, que passa a ser o ponto de embarque padrão do aluno; exige `rota`), `instituicao` (nome) e `rota` (nome). O resultado sai por linha: CRIADO, RENOVADO, PULADO ou INVALIDO. Veja `scripts/exemplo_convites.csv`.

## 📁 Estrutura do Projeto

```
buska-backend/
├── app/                    # Código da aplicação
│   ├── api/
│   │   ├── controllers/    # Lógica dos endpoints
│   │   └── routes/         # Definição das rotas
│   ├── core/
│   │   ├── auth.py         # Autenticação JWT
│   │   └── config.py       # Configurações
│   ├── models/             # Modelos SQLAlchemy
│   └── services/           # Serviços de negócio
├── database/               # Scripts SQL
│   ├── init.sql            # Schema e extensões
│   └── populate.sql        # Dados iniciais
├── docs/                   # Documentação da API
│   └── endpoints/          # Specs YAML (Swagger)
├── infra/
│   ├── database.yml        # Docker Compose (dev)
│   └── terraform/          # Infraestrutura (OpenStack)
├── ansible/                # Playbooks de automação
│   ├── setup-dev.yml       # Setup local
│   ├── run-docker.yml      # Deploy Docker
│   └── deploy-prod.yml     # Deploy OpenStack
├── tests/                  # Testes automatizados
├── Dockerfile              # Build de produção
├── docker-compose.prod.yml # Orquestração (prod)
├── Makefile                # Automação de comandos
├── setup.sh                # Setup automatizado
├── start.sh                # Setup + Docker
└── pyproject.toml          # Dependências Python
```

## Variáveis de Ambiente

Copie o `.env.example` para `.env.prod` e configure:

```bash
# Database
DB_USER=buska_user
DB_PASSWORD=senha_segura_aqui
DB_NAME=buska_db

# API
API_PORT=5000
DEBUG=false
JWT_SECRET_KEY=chave_jwt_longa_e_aleatoria
JWT_EXPIRES_HOURS=2
```

## 📚 Documentação

### Documentação da API
A documentação completa e interativa da API está disponível em:
- **Swagger UI**: http://localhost:5000/docs
- **ReDoc**: http://localhost:5000/redoc

Principais endpoints:
- `POST /auth/login` - Autenticar
- `POST /auth/register` - Criar conta
- `GET /rotas` - Listar rotas
- `GET /viagens` - Listar viagens
- `GET /me` - Dados do usuário autenticado

## 🔒 Segurança

O backend implementa múltiplas camadas de segurança:

### Autenticação & Autorização
- **JWT** com expiração configurável (padrão: 2 horas)
- **RBAC** (Role-Based Access Control): ALUNO, MOTORISTA, GESTOR
- **Isolamento por Prefeitura** (tenant isolation)

### Proteções Implementadas
- ✅ **Security Headers**: CSP, XSS Protection, HSTS, etc.
- ✅ **Audit Logging**: Registro de todas operações sensíveis
- ✅ **Request ID Tracking**: Rastreamento de requisições

## 🚢 Deployment

### OpenStack (Terraform + Ansible)

```bash
cd infra/terraform
terraform init
terraform plan
terraform apply

# Depois, deploy via Ansible
ansible-playbook ansible/deploy-prod.yml
```

### Docker Local

```bash
./start.sh
```

Containers iniciados:
- `buska_api` - Flask API com Gunicorn (porta 5000)
- `buska_db_prod` - PostgreSQL + PostGIS (porta 5432)

## 🐛 Troubleshooting

### Erro: Import errors para utilitários novos
```bash
# Reinstalar dependências
pip install -e "."
```

### Logs não estão em formato legível
```bash
# Adicionar DEBUG=true no .env
echo "DEBUG=true" >> .env

# Limpar cache e reiniciar
find . -type d -name "__pycache__" -exec rm -r {} +
make run
```

### Type checking errors (mypy)
```bash
# Rodar com configurações menos estritas
mypy app --no-strict-optional --ignore-missing-imports
```
