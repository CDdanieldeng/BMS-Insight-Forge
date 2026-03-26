# Insight Forge

A GenAI-powered webapp that fills business plan slide decks. Uses AI to populate Customer Segmentation and Messaging Strategy modules based on uploaded support documents.

## Architecture

- **Frontend**: React (Vite) in `insight-forge-web`
- **Backend**: FastAPI with two logical services:
  - **Generation** (Orchestrator + LLM): Document ingest, context retrieval, and fill orchestration
  - **Fill Engine**: python-pptx for table structure extraction and filling

## Quick Start

1. Copy `.env.example` to `.env` and set your LLM API keys (e.g., `OPENAI_API_KEY`).
2. Run the backend with Docker Compose:
   ```bash
   docker compose up --build
   ```
3. In another terminal, run the web UI (`insight-forge-web` defaults to [http://localhost:5173](http://localhost:5173); set `VITE_BACKEND_URL` if the API is not at `http://localhost:8001`):
   ```bash
   cd insight-forge-web && npm install && npm run dev
   ```

## Development (Local)

1. Install backend dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

2. Run backend (Terminal 1):
   ```powershell
   .\run_backend.ps1
   ```
   Or manually:
   ```bash
   cd backend && set PYTHONPATH=%CD% && python -m uvicorn main:app --reload --port 8001
   ```

3. Run the React app (Terminal 2):
   ```bash
   cd insight-forge-web && npm install && npm run dev
   ```

4. Open the URL printed by Vite (typically http://localhost:5173).

5. From a VM (backend only example):
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8001
   ```
