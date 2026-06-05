#AI — Python Voice Agent

🌐 **Live Demo**: [lhw300.xyz](https://lhw300.xyz) — try the clinic voice agent live

Python AI agent layer for the enterprise call center platform. Handles intent classification, multi-turn dialogue, two-stage RAG retrieval, and L1/L2 semantic caching.

---

## Key Features

- **7-class Intent Classification** — QUERY / COMMAND / GREETING / FEEDBACK / CHITCHAT / INFORM / ACK with entity normalization and category routing
- **Two-stage RAG Pipeline** — vector coarse ranking (pgvector) + cross-encoder batch rerank with fast-track circuit breaker
- **L1 / L2 Redis Cache** — two-tier semantic cache intercepts repeat and paraphrased queries before RAG; exact match under 5ms, semantic match under 300ms
- **Multi-turn Dialogue** — `ChatSession` maintains conversation history with refined query rewriting and cross-turn context
- **Urgent Fast-track** — emergency keywords bypass RAG entirely, response under 1 second
- **Conditional Debug Logging** — all verbose log output (candidates, fullCtx, AI response, messages) controlled via `ai.conf` switches

---

## Tech Stack

| Layer | Component |
|-------|-----------|
| Language | Python 3.10+ |
| LLM | OpenAI gpt-4o / gpt-4o-mini (configurable) |
| Embedding | OpenAI text-embedding-3 / local BGE |
| Reranking | CrossEncoder batch rerank |
| Vector DB | PostgreSQL + pgvector |
| Cache | Redis (L1 exact match + L2 semantic) |
| API | FastAPI |

---

## Project Structure

```
├── session/
│   ├── session_manager.py      # Global init, model router assembly, session lifecycle
│   └── chat_session.py         # Session core: multi-turn dialogue, RAG pipeline, K1/K2 cache
├── search/
│   ├── search_service.py       # pgvector retrieval, embedding, two-stage search
│   └── cache_service.py        # L1/L2 Redis cache (k1_get/k1_put/k2_get/k2_put)
├── intent/
│   ├── intent_classifier.py    # LLM-based 7-class intent classifier
│   ├── intent_dispatcher.py    # Routes intent to registered handler
│   └── intent_result.py        # IntentResult dataclass (intent, sentiment, refined_query)
├── handler/
│   ├── query_handler.py        # QUERY → askByQueryMode
│   ├── command_handler.py      # COMMAND → TRANSFER / REPLAY / VOL_UP / HANGUP
│   ├── greeting_handler.py     # GREETING response
│   ├── feedback_handler.py     # FEEDBACK handling
│   ├── chitchat_handler.py     # CHITCHAT free-form response
│   ├── ack_handler.py          # ACK (affirm / negate)
│   └── inform_handler.py       # INFORM slot filling
├── models.py                   # ChatAnswer, Action enum
├── ai_config.py                # Config loader + AiConfig.log() conditional logger
├── config/
│   ├── redis_convert_health.txt  # L1 normalization rules (120+ patterns)
│   └── redis_faq_health.txt      # (retired — no pre-seeded FAQ)
└── test/
    ├── cache_test_clinic_runner.py   # L1/L2 cache integration test (clinic scenario)
    └── rag_test_clinic_runner.py     # Full RAG pipeline test (clinic scenario)
```

---

## Configuration

`ai.conf` key settings:

```properties
# Model
llm.type=openai

# Redis cache
redis.host=localhost
redis.port=6379
redis.db=0
redis.convert.file=config/redis_convert_health.txt

# RAG thresholds
similarity.threshold=0.82
rerank.trigger.max=0.5
rescue.score=0.6

# Log controls (0 = off, N = print first N chars)
log.candidates.max=3
log.fullctx.chars=200
log.ai.response.chars=200
log.messages.chars=0
log.intent.input.chars=0
log.prompt.preview.chars=100
```

---

## L1 / L2 Cache

Two-tier Redis cache sits between intent classification and the RAG pipeline.

```
User input
  ↓ convert() — normalize (punctuation, filler words, synonym rules)
  ↓ K1 exact match (Redis String, MD5 hash key)     ~1ms
  ↓ embed() → K2 semantic match (Redis Hash, cosine similarity)  ~300ms
  ↓ RAG pipeline                                    ~1500ms
  ↓ write back to K1 + K2
```

Cache key uses `refined_query` from intent classifier, ensuring paraphrased inputs sharing the same semantic meaning hit the same cache entry.

---

## Tests

### Cache integration test (clinic scenario)

```bash
python test/cache_test_clinic_runner.py [config_path]
```

Three rounds:
- **Round 1** — warm up: 5 clinic questions go through full RAG pipeline, write K1 + K2
- **Round 2** — exact repeat: same 5 questions, all should hit K1 (< 2000ms)
- **Round 3** — paraphrase: 5 rephrased versions in a new session, should hit K1 or K2 via intent rewrite

### Text chat test tool

`chat_test.py` is an interactive command-line tool that sends messages to the running FastAPI agent and prints the AI response. Useful for quick manual testing without a phone or WebRTC client.

```bash
python test/chat_test.py
```

Commands during session:
- Type any message to chat
- `new` — start a fresh session (new `sn`)
- `quit` / `exit` — exit

Configure `BASE_URL` and `vo_id` at the top of the file to match your deployment.

### RAG pipeline test (clinic scenario)

```bash
python test/rag_test_clinic_runner.py [config_path]
```

Covers QUERY, COMMAND, GREETING, FEEDBACK, CHITCHAT intents across a simulated clinic call flow.

---

## Getting Started

```bash
pip install -r requirements.txt

# Start Redis (local)
sudo nohup /usr/bin/redis-server /etc/redis/redis.conf &

# Run cache test
python test/cache_test_clinic_runner.py e:/ai
```

---

## PostgreSQL Setup

**1. Install PostgreSQL and pgvector**
```bash
sudo apt install postgresql postgresql-contrib -y
sudo apt install postgresql-16-pgvector -y
```

**2. Create database and enable extension**
```sql
CREATE DATABASE lcallai;
\c lcallai
CREATE EXTENSION IF NOT EXISTS vector;
```

**3. Create knowledge table** (1024 = embedding dimension, adjust if using a different model)
```sql
CREATE TABLE health_knowledge_1024 (
    id          VARCHAR(64) PRIMARY KEY,
    category    VARCHAR(50),
    summary     VARCHAR(255),
    content     TEXT,
    source_name VARCHAR(100),
    is_active   BOOLEAN DEFAULT true,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding   vector(1024)
);

CREATE INDEX ON health_knowledge_1024 USING ivfflat (embedding vector_cosine_ops);
```

**4. Configure `ai.conf`**
```properties
db.postgres.url=jdbc:postgresql://localhost:5432/lcallai
db.postgres.user=postgres
db.postgres.password=your_password
db.postgres.table.online=health_knowledge_1024
```

**5. Ingest knowledge base** (TXT format: `Category | Summary | Content` per line)
```bash
python search/ingestion_service.py e:/ai
```
