Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/AGENTS.md#1-1), lines 1 to 100

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/cyber_law_service.py#1-1), lines 1 to 100

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/core_decision_service.py#1-1), lines 1 to 100

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/cyber_law_service.py#100-100), lines 100 to 200

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/core_decision_service.py#100-100), lines 100 to 191

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/complaint_service.py#1-1), lines 1 to 80

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/complaint_draft_service.py#1-1), lines 1 to 80

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/news_service.py)

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/schemas/requests.py)

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/api/routes)

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/content_enhancement_service.py#1-1), lines 1 to 80

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/api/routes/data_sources.py#1-1), lines 1 to 150

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/core/config.py)

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/api/routes/data_sources.py#150-150), lines 150 to 150

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/schemas/responses.py#1-1), lines 1 to 60

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/api/routes/data_sources.py#150-150), lines 150 to 150

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/cyber_law_service.py#200-200), lines 200 to 200

Searched for regex `@router\.` (`CyberGuard_Project` · `cyberGuard/app/api/routes/data_sources.py`), 9 results

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/cyber_law_service.py#100-100), lines 100 to 100

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/api/routes/data_sources.py#150-150), lines 150 to 392

Now I have a full picture of the system. Let me synthesize the analysis.  

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/schemas/responses.py#55-55), lines 55 to 60

Read [](file:///h%3A/PGAGI/CyberGuard_Project/cyberGuard/app/services/location_service.py)

---

## Agentic RAG Analysis for CyberGuard

### What the project currently is

CyberGuard is a **linear, multi-step pipeline** where the frontend manually chains 4-5 separate API calls:

```
input → /content-enhancement → /core-decision → /get-cyber-laws → /generate-complaint
```

The existing "RAG" in cyber_law_service.py is **passive and single-shot**:
- Fixed `top_k=4` FAISS `similarity_search_with_score` on one jurisdiction index
- The `core_cybercrime` string from core-decision is used as-is as the query — no refinement
- No relevance quality check on what came back
- No iteration, no agent loop

Every LLM call across all services is a **one-shot Gemini call with structured output** (function calling in `mode="ANY"`). The function calling is used purely for schema enforcement, not for tool-use reasoning.

---

### Yes — there is significant scope. Here's exactly where and how:

---

#### 1. Multi-Query / Adaptive Retrieval in cyber_law_service.py
**Biggest gap.** The current `_retrieve_docs_with_metadata` fires a single vector query with the raw `core_cybercrime` summary. An agentic loop improves this dramatically:

- **Query decomposition**: Decompose `core_cybercrime` into 2–3 sub-queries (e.g., crime type, victim rights angle, regulatory angle) and merge retrieved docs, deduplicated.
- **Relevance gating**: After retrieval, use an LLM to score whether the top-k docs are actually relevant enough. If not, reformulate the query and re-retrieve — the agent decides to loop.
- **Multi-index retrieval**: Currently only one FAISS index per jurisdiction. An agent could query all three (India, UK, USA) and reason over which laws apply, rather than hardcoding jurisdiction.
- This maps directly to the `retrieve_laws()` + `analyze_cyber_laws()` functions — the agent replaces the static `_retrieve_docs_with_metadata` call.

---

#### 2. A Single Agentic `/analyze` Endpoint (Orchestrator Agent)

The most architecturally impactful addition. Right now the **frontend** is the orchestrator — it calls APIs in sequence. An agent with tools could own the entire reasoning loop:

```
POST /analyze { source, source_type, content, language, location }
```

The agent would have tools registered as Python callables:
- `enhance_content(content, source_type)` → cleaned text
- `analyze_bullying(content, source, ...)` → core decision
- `retrieve_laws(core_cybercrime, jurisdiction)` → law snippets
- `analyze_cyber_laws(...)` → legal analysis
- `generate_complaint_letter(...)` → final complaint

The agent (Gemini with `tool_choice="auto"`) **plans and sequences these tool calls itself**, handles conditional logic (e.g., skip complaint draft if `bullying=no`), and retries on partial failures. This matches how Gemini's native function calling with `mode="AUTO"` is designed to work — the existing `_DECISION_FUNCTION` and `_COMPLAINT_FUNCTION` schemas already show the team understood function schemas.

---

#### 3. Iterative RAG with Self-Critique in core_decision_service.py

Currently core_decision_service.py returns `core_cybercrime` in a single pass with a flat prompt. An agentic enhancement:

- After the initial decision, a **second agentic pass** checks: "Is the `core_cybercrime` description specific enough to retrieve meaningful laws?" 
- If not, it refines — the agent generates a richer legal query before handing off to the RAG layer.
- This fixes the root issue where vague `core_cybercrime` summaries produce poor FAISS recall.

---

#### 4. Dynamic RAG Sources (Tool-Augmented Retrieval)

The static FAISS indexes only cover 3 jurisdictions and are frozen at build time. An agent could add live tools:
- `search_news(query)` — already exists via news_service.py + web_service.py
- `lookup_rbi_rule(topic)` — RBI_rules.json and TRAI_rules.json already exist as structured JSON, not vectorized
- The agent decides at runtime whether static FAISS retrieval is enough or whether to call a live web tool

The RBI/TRAI JSON files are a **completely unused RAG source** right now — an agent with a tool to query them would immediately improve legal coverage.

---

#### 5. Complaint Generation with Feedback Loop

complaint_draft_service.py is pure one-shot generation. An agentic version:
- Generates a draft
- Self-critiques: "Does this draft cite the applicable laws properly? Is the complainant's jurisdiction reflected?"
- Revises once based on its own critique (one-loop reflection)
- This is a classic **Reflect + Revise** agentic pattern and works well within Gemini's token budget

---

### Summary Table

| Location | Current Pattern | Agentic RAG Upgrade |
|---|---|---|
| cyber_law_service.py `_retrieve_docs_with_metadata` | Single-shot FAISS, 1 query, fixed k | Multi-query, relevance gating, re-retrieval loop |
| Frontend pipeline | Frontend chains 4 API calls | Single `/analyze` agent endpoint with tool use |
| core_decision_service.py | One-shot crime summary | Iterative query refinement before RAG handoff |
| `CyberLawsData/RBI_rules.json`, `TRAI_rules.json` | **Not used** | Agent tool for live rule lookup |
| complaint_draft_service.py | One-shot generation | Generate → Self-critique → Revise loop |
| location_service.py (3 jurisdictions only) | Hard-coded | Agent queries all indexes, reasons about applicability |

The biggest ROI in order: **(1) multi-query adaptive retrieval**, **(2) the orchestrator agent endpoint**, **(3) surfacing the RBI/TRAI JSON as a tool**. The infrastructure (Gemini client, FAISS, function schemas) is already in place — the agentic layer sits on top without requiring a new model or vector store.