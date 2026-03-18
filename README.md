# Insight Forge

A GenAI-powered webapp that fills business plan slide decks. Uses AI to populate Customer Segmentation and Messaging Strategy modules based on uploaded support documents.

## Architecture

- **Frontend**: Streamlit (PoC; will be replaced by React for MVP)
- **Backend**: FastAPI with three logical services:
  - **Generation** (Orchestrator + LLM): Single gateway, coordinates retriever and fill engine
  - **Retriever**: Converts pptx/docx to markdown via markitdown; returns text (no embedding for PoC)
  - **Fill Engine**: python-pptx for table structure extraction and filling

## Quick Start

1. Copy `.env.example` to `.env` and set your LLM API keys (e.g., `OPENAI_API_KEY`).
2. Run with Docker Compose:
   ```bash
   docker compose up --build
   ```
3. Open http://localhost:8501 for the Streamlit app.

## Development (Local)

1. Install dependencies:
   ```bash
   pip install -r backend/requirements.txt
   pip install -r frontend/requirements.txt
   ```

2. Run backend (Terminal 1):
   ```powershell
   .\run_backend.ps1
   ```
   Or manually:
   ```bash
   cd backend && set PYTHONPATH=%CD% && python -m uvicorn main:app --reload --port 8001
   ```

3. Run frontend (Terminal 2):
   ```powershell
   .\run_frontend.ps1
   ```
   Or manually:
   ```bash
   cd frontend && streamlit run app.py
   ```

4. Open http://localhost:8501


5. From VM
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8001
   streamlit run app.py --server.address 0.0.0.0 --server.port 8501
   ```
