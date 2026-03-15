# BMS Insight Forge: Refactoring Plan

> Goal: Organize the codebase from **module → slide** level, with consistent **cowork agent → table fill agent → fix table agent** per module, and make it easy to add new modules.

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 1** | ✅ Done | `modules/` created with registry, customer_segmentation (table_fill_agent), swot_analysis + messaging_strategy stubs. Orchestrator uses `get_module()` for CS path. Lazy init for TableFillAgent so app starts without API keys. |
| Phase 2 | Pending | Move cowork agents into modules |
| Phase 3 | Pending | Extract table fill agents for SWOT, MS |
| Phase 4 | Pending | Fix table agent refactor |
| Phase 5 | Pending | Cleanup, remove legacy paths |

---

## 1. Target Architecture Overview

```
modules/
├── customer_segmentation/
│   ├── __init__.py
│   ├── config.py              # module config, slide metadata, key questions
│   ├── cowork_agent.py         # CoworkOrchestrator (starter consultant)
│   ├── table_fill_agent.py     # generates table from docs + context
│   ├── fix_table_agent.py      # applies user feedback to refine table
│   └── slides/
│       ├── slide1.py           # prompt builder + any slide-specific logic
│       └── slide2.py
├── swot_analysis/
│   ├── __init__.py
│   ├── config.py
│   ├── cowork_agent.py
│   ├── table_fill_agent.py
│   └── slides/
│       └── slide1.py           # 4-column SWOT table
├── messaging_strategy/
│   ├── __init__.py
│   ├── config.py
│   ├── table_fill_agent.py     # no cowork yet
│   └── slides/
│       └── slide3.py
└── _registry.py                # ModuleRegistry: discover and dispatch by module
```

**Shared services** (unchanged or lightly refactored):
- `retriever/` – document ingestion, BM25 search
- `fill_engine/` – PPTX parse/write (no LLM)
- `shared/` – logging, config

---

## 2. Three Agent Roles (Consistent Naming)

| Role | Current Location | New Location | Responsibility |
|------|------------------|--------------|-----------------|
| **Cowork Agent** | `cowork_agent/orchestrator.py`, `swot_orchestrator.py` | `modules/<module>/cowork_agent.py` | Starter: conversational consultant to gather brief, files, segment names. Produces `cowork_guidance` for table fill. |
| **Table Fill Agent** | `orchestrator.run_fill()` + `CustomerSegmentationAgent` + inline SWOT/MS logic | `modules/<module>/table_fill_agent.py` | Generates table content from documents + prior slides + cowork guidance. |
| **Fix Table Agent** | `generation/agent.py` (`apply_feedback`) | `modules/<module>/fix_table_agent.py` or shared `fix_table/` | Applies user feedback to refine table. Can be shared if logic is generic, or per-module if needed. |

**Naming convention:**
- `CoworkAgent` / `cowork_agent` – starter, brief-gathering
- `TableFillAgent` / `table_fill_agent` – initial table generation
- `FixTableAgent` / `fix_table_agent` – feedback-driven refinement

---

## 3. Module Registry Pattern

**Goal:** Add a new module by creating a folder and registering it—no edits to core orchestration.

```python
# modules/_registry.py

from typing import Protocol

class ModuleConfig(Protocol):
    module_id: str           # e.g. "customer_segmentation"
    display_name: str        # e.g. "Customer Segmentation"
    slide_indexes: list[int] # which slide indices belong to this module

class ModuleProvider(Protocol):
    def get_config(self) -> ModuleConfig: ...
    def get_cowork_agent(self) -> CoworkAgent | None: ...
    def get_table_fill_agent(self) -> TableFillAgent: ...
    def get_fix_table_agent(self) -> FixTableAgent: ...

REGISTRY: dict[str, ModuleProvider] = {}

def register_module(provider: ModuleProvider) -> None:
    cfg = provider.get_config()
    REGISTRY[cfg.module_id] = provider

def get_module(module_name: str) -> ModuleProvider | None:
    normalized = module_name.lower().strip().replace(" ", "_")
    return REGISTRY.get(normalized)
```

Each module’s `__init__.py` calls `register_module()` on import.

---

## 4. Module → Slide Hierarchy

**Current:** Slides are inferred from `slide_info` and `get_slides_by_module()`. Module names are scattered (`"Customer Segmentation"`, `"SWOT Analysis"`, `"Messaging Strategy"`).

**Target:**
1. **Module config** defines:
   - `module_id` (normalized for code)
   - `display_name` (for UI)
   - `slide_indices` or mapping to slide identifiers
2. **Slide config** lives under `modules/<module>/slides/slideN.py`:
   - Row labels / indexes
   - Prompt builder
   - Any slide-specific postprocessing (e.g. MS slide3 "prioritized segment" row)

**Example:**

```python
# modules/customer_segmentation/config.py
MODULE_ID = "customer_segmentation"
DISPLAY_NAME = "Customer Segmentation"
SLIDES = [
    {"id": "slide1", "indexes": ["Segment 1", "Segment 2", ...]},
    {"id": "slide2", "indexes": [...]},
]
```

---

## 5. Migration Steps

### Phase 1: Introduce Module Structure (Non-Breaking)
1. Create `modules/` directory and `_registry.py`.
2. Create `modules/customer_segmentation/` and move:
   - `generation/slide_prompts/customer_segmentation/*` → `modules/customer_segmentation/slides/`
   - `CustomerSegmentationAgent` logic → `modules/customer_segmentation/table_fill_agent.py`
3. Create `ModuleProvider` for Customer Segmentation that wraps existing code.
4. Update orchestrator to call `get_module(module).get_table_fill_agent()` when available, else fallback to current logic.
5. No API or UI changes yet.

### Phase 2: Move Cowork Agents
1. Move `CSCoworkOrchestrator` → `modules/customer_segmentation/cowork_agent.py`.
2. Move `SwotCoworkOrchestrator` → `modules/swot_analysis/cowork_agent.py`.
3. Update `cowork_agent/router.py` to use registry:
   ```python
   provider = get_module(req.module)
   if provider and provider.get_cowork_agent():
       return provider.get_cowork_agent().handle_turn(req)
   raise HTTPException(400, "Cowork not available for this module")
   ```
4. Add `modules/swot_analysis/` with config, table_fill_agent (extract SWOT logic from orchestrator), slides.

### Phase 3: Extract Table Fill Agents
1. Extract `generate_table_content` + SWOT/MS-specific branches from `orchestrator.py` into:
   - `customer_segmentation/table_fill_agent.py`
   - `swot_analysis/table_fill_agent.py`
   - `messaging_strategy/table_fill_agent.py`
2. Move SWOT prompts from inline orchestrator into `modules/swot_analysis/slides/slide1.py`.
3. Slim down `orchestrator.run_fill()` to:
   - Resolve module from registry
   - Delegate to `module.get_table_fill_agent().fill(...)`
   - Handle shared concerns (retrieval, caching) via a shared pipeline

### Phase 4: Fix Table Agent
1. If logic is generic: create `modules/shared/fix_table_agent.py` and have all modules use it.
2. If module-specific: add `fix_table_agent.py` per module where needed.
3. Update `generation/router.py` chat endpoint to use registry.

### Phase 5: Cleanup and Consolidation
1. Remove `generation/customer_segmentation_agent.py`, inline SWOT logic from orchestrator.
2. Remove `cowork_agent/orchestrator.py`, `swot_orchestrator.py` (logic now in modules).
3. Consolidate `generation/slide_prompts/` – prompts live in modules.
4. Update `config/key_business_questions.md` usage: each module’s config can reference it or embed questions.

---

## 6. Shared vs Module-Specific

| Component | Shared | Module-Specific |
|-----------|--------|-----------------|
| Retrieval (BM25, facet gating) | ✅ `retriever/`, `evidence_pipeline` | - |
| Query enhancement | ✅ `query_enhancer` | - |
| Context merge (prior tables) | ✅ utility in `modules/_common.py` | Module defines *which* prior slides to use |
| Slide prompts | - | ✅ Per slide in `slides/slideN.py` |
| Segment extraction | ✅ `segment_extractor` | CS uses it; others may use different strategies |
| Fix table routing (need context?) | ✅ in fix_table_agent | Module-specific prompt for modification |
| Cowork workflow states | ✅ `workflow.py`, `event_interpreter` | Module defines phases, brief schema |

---

## 7. Adding a New Module (After Refactor)

1. Create `modules/new_module/`:
   - `config.py` – MODULE_ID, DISPLAY_NAME, SLIDES
   - `table_fill_agent.py` – implements `TableFillAgent.fill(...)`
   - `cowork_agent.py` (optional) – implements `CoworkAgent.handle_turn(...)`
   - `slides/slideN.py` – prompt builders
2. In `__init__.py`: implement `ModuleProvider`, call `register_module()`.
3. Add to `config/key_business_questions.md` if needed.
4. Frontend: add `"New Module"` to `MODULES` and `get_slides_by_module` mapping if backend slide-info doesn’t already expose it.

**No changes to:**
- `orchestrator.run_fill()` core loop (dispatches via registry)
- `cowork_agent/router` (dispatches via registry)
- `generation/router` chat (dispatches via registry)

---

## 8. Naming Improvements

| Current | Proposed |
|---------|----------|
| `CustomerSegmentationAgent` | `CustomerSegmentationTableFillAgent` (or just `TableFillAgent` inside the module) |
| `CSCoworkOrchestrator`, `SwotCoworkOrchestrator` | `CoworkAgent` (protocol), module-specific impls |
| `apply_feedback` (in agent.py) | `FixTableAgent.apply_feedback()` |
| `run_fill` | Keep; it orchestrates. Internally calls `TableFillAgent.fill()`. |
| `generation/agent.py` | Split: `fix_table/` or per-module `fix_table_agent.py` |
| `orchestrator` (does fill + routing) | `orchestrator` → thin dispatcher; heavy logic in module agents |

---

## 9. File Structure Summary (Target)

```
backend/
├── main.py
├── modules/
│   ├── _registry.py
│   ├── _common.py              # shared: prior table context, retrieval helpers
│   ├── customer_segmentation/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── cowork_agent.py
│   │   ├── table_fill_agent.py
│   │   ├── fix_table_agent.py   # or use shared
│   │   └── slides/
│   │       ├── slide1.py
│   │       └── slide2.py
│   ├── swot_analysis/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── cowork_agent.py
│   │   ├── table_fill_agent.py
│   │   └── slides/
│   │       └── slide1.py
│   └── messaging_strategy/
│       ├── __init__.py
│       ├── config.py
│       ├── table_fill_agent.py
│       └── slides/
│           └── slide3.py
├── generation/                  # slimmed down
│   ├── router.py
│   ├── orchestrator.py          # thin: retrieval + registry dispatch
│   ├── evidence_pipeline.py
│   ├── query_enhancer.py
│   ├── segment_extractor.py
│   ├── key_questions.py
│   └── llm_client.py
├── fill_engine/                 # unchanged
├── retriever/                   # unchanged
├── cowork_agent/                # slimmed to router + shared workflow
│   ├── router.py                # dispatches to modules
│   ├── workflow.py
│   ├── event_interpreter.py
│   ├── session_store.py
│   └── models.py
├── shared/
└── ...
```

---

## 10. Risk Mitigation

- **Phase 1 first:** Introduce module structure and registry without removing old code. Use feature flag or `get_module()` fallback to old path.
- **Tests:** Keep existing integration tests; add module-level unit tests for each `TableFillAgent`, `FixTableAgent`.
- **Incremental:** One module at a time (CS → SWOT → MS).
- **Frontend:** Minimal changes; backend API (`/generation/fill`, `/generation/chat`, `/cowork-agent/...`) stays the same.
