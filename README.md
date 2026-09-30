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

## 🔐 Secrets

Never commit `.env`, API keys, database passwords, or JWT secrets.
Use `.env.example` as the template; the real `.env` is git-ignored.

---

## 🗺️ Roadmap

- [x] **Phase 0** — Project initialization & scaffolding
- [ ] **Phase 1** — Database & core models
- [ ] **Phase 2** — Firewall (prompt-injection detection)
- [ ] **Phase 3** — Trust engine & policies
- [ ] **Phase 4** — Agents + RAG
- [ ] **Phase 5** — Frontend dashboard
- [ ] **Phase 6** — Attack scenarios & evaluation
- [ ] **Phase 7** — Deployment

---

## 📄 License

TBD.
