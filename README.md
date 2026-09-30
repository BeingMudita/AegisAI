# 🛡️ AegisAI

**A Zero-Trust Security Layer for Autonomous AI Agents**

AegisAI wraps LLM-powered agent systems in a defensive perimeter — a prompt-injection
firewall, a per-tool trust engine, policy enforcement, and full telemetry — so that
autonomous agents can use tools and knowledge safely, even under adversarial input.

> Status: **Phase 0 — Project initialization** ✅

---

## ✨ What it does

| Layer | Responsibility |
|-------|----------------|
| **Firewall** | Detects & blocks prompt-injection / jailbreak attempts on inbound content |
| **Trust Engine** | Scores agents, tools, and data sources; gates risky actions |
| **Policies** | Declarative rules (YAML) for what agents are allowed to do |
| **Agents** | LangGraph-orchestrated agent workflows |
| **RAG** | Retrieval over a pgvector knowledge base with Sentence-Transformer embeddings |
| **Tools** | Sandboxed, permissioned tool integrations |
| **Telemetry** | Structured audit logging of every decision |

---

## 🧱 Tech Stack

**Backend** — Python · FastAPI · SQLAlchemy · Pydantic
**AI** — LangGraph · Ollama (local LLMs) · Sentence-Transformers
**RAG** — Custom RAG / LlamaIndex
**Database** — PostgreSQL · pgvector
**Frontend** — React · TypeScript · Vite · Tailwind · Recharts
**Deployment** — Docker · Render · Vercel · Supabase

---

## 📁 Repository Structure

```
AegisAI/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes
│   │   ├── agents/       # LangGraph agent orchestration
│   │   ├── rag/          # Retrieval-augmented generation
│   │   ├── trust/        # Trust scoring engine
│   │   ├── firewall/     # Prompt-injection detection
│   │   ├── policies/     # Policy definitions & enforcement
│   │   ├── tools/        # Agent tool integrations
│   │   ├── telemetry/    # Audit logging & metrics
│   │   └── database/     # Models, sessions, migrations
│   └── tests/
├── frontend/             # React + Vite dashboard
├── attack-scenarios/     # Red-team test cases
├── evaluation/           # Benchmarks & metrics
├── docker/               # Dockerfiles & compose
├── docs/                 # Architecture & design docs
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- Node.js 20+
- Docker & Docker Compose
- [Ollama](https://ollama.com) running locally

### 1. Clone & configure
```bash
git clone <repo-url> AegisAI
cd AegisAI
cp .env.example .env      # then edit .env with real values
```

### 2. Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit http://localhost:8000/docs for the interactive API.

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```

### 4. Full stack via Docker
```bash
docker compose -f docker/docker-compose.yml up --build
```

---

## 🔎 RAG Pipeline (Phase 3)

Ordinary retrieval-augmented generation over the sample dataset in `data/`:

```
PDF / TXT / MD → text extraction → chunking → embeddings → PostgreSQL + pgvector
Question → embedding → cosine vector search → top-K chunks → LLM → answer
```

- **Embeddings**: Sentence-Transformers (`EMBEDDING_MODEL`), with a deterministic
  hashing fallback when the library/model is unavailable (offline/CI).
- **LLM**: Ollama (`MODEL_NAME`) via `/api/generate`.
- **Endpoints**: `POST /api/retrieval/search` (top-K chunks) and
  `POST /api/retrieval/ask` (full RAG answer).
- **Ingestion CLI**: `python -m app.rag.ingest ../data`

---

## ✅ Testing What's Built

### A. Automated tests (no external services needed)
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # (Unix: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```
Covers config, JWT auth + RBAC, all 12 ORM models, the policy engine, and RAG
components (chunking, embeddings, PDF/MD extraction, prompt building).

### B. End-to-end RAG (needs Docker + Ollama)
```bash
# 1. Start PostgreSQL + pgvector
docker compose -f docker/docker-compose.yml up -d db

# 2. Start Ollama and pull the model
ollama serve            # (in its own terminal)
ollama pull llama3.1:8b

# 3. Generate sample data (once) and initialize the DB
python data/generate_sample_data.py
cd backend
python -m app.database.init_db

# 4. Ingest the documents
python -m app.rag.ingest ../data

# 5. Run the API
uvicorn app.main:app --reload
```
Then, in another terminal:
```bash
# Log in (get a JWT)
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -d "username=analyst&password=analyst123" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Vector search
curl -s -X POST localhost:8000/api/retrieval/search \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Which invoices are overdue?","top_k":3}'

# Full RAG answer
curl -s -X POST localhost:8000/api/retrieval/ask \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"Which invoices are overdue?"}'
```
Expected: chunks from `invoice_03`, `invoice_42`, and the reminder emails rank
highest; the answer names **INV-0003** and **INV-0042** as overdue.

Interactive API docs: http://localhost:8000/docs

---

## 🔐 Secrets

Never commit `.env`, API keys, database passwords, or JWT secrets.
Use `.env.example` as the template; the real `.env` is git-ignored.

---

## 🗺️ Roadmap

- [x] **Phase 0** — Project initialization & scaffolding
- [x] **Phase 1** — Backend foundation (API structure, config, JWT auth)
- [x] **Phase 2** — Database & policy system
- [x] **Phase 3** — Basic RAG pipeline (ingest → embed → retrieve → answer)
- [ ] **Phase 4** — Firewall (prompt-injection detection)
- [ ] **Phase 5** — Trust engine
- [ ] **Phase 6** — Agents
- [ ] **Phase 7** — Frontend dashboard
- [ ] **Phase 8** — Attack scenarios & evaluation
- [ ] **Phase 9** — Deployment

---

## 📄 License

TBD.
