# Insight Forge

A GenAI-powered web application that helps teams work on business plan slide decks. It combines document ingestion, retrieval-augmented context, and structured fills for modules such as **Customer Segmentation** and **Messaging Strategy**. The UI drives a **FastAPI** backend that orchestrates LLM workflows and fills **PowerPoint** tables via **python-pptx**.

---

## Technology stack

### Frontend (`insight-forge-web`)

| Area | Technology |
|------|------------|
| Runtime / UI | **React 19**, **TypeScript** |
| Build / dev server | **Vite 8** |
| Routing | **react-router-dom** |
| Server state / async | **TanStack React Query** |
| Client state | **Zustand** |
| HTTP | **Axios** (shared base URL, timeouts, auth interceptor) |
| Styling | **Tailwind CSS 4** (`@tailwindcss/vite`) |
| Markdown in UI | **react-markdown**, **remark-gfm** |
| Identity (optional) | **Microsoft Authentication Library (MSAL)** — `@azure/msal-browser`, `@azure/msal-react` (authorization code flow with PKCE for SPA) |

Environment variables for the web app use the **`VITE_`** prefix. Vite is configured with **`envDir`** pointing at the **repository root**, so you can keep frontend and backend settings in a single **`.env`** file next to **`.env.example`**.

### Backend (`backend`)

| Area | Technology |
|------|------------|
| API framework | **FastAPI** |
| ASGI server | **Uvicorn** |
| Config | **python-dotenv** (loads repo-root `.env`) |
| API auth (optional) | **PyJWT** (RS256) + Microsoft Entra **JWKS** for access token validation |
| Deck I/O | **python-pptx**, **PyMuPDF**, **matplotlib** (rendering / previews where applicable) |
| Document conversion | **markitdown** |
| LLM | **OpenAI** SDK; **LangChain**, **LangGraph** |
| Embeddings / retrieval | **sentence-transformers**, custom retriever/orchestration code |
| Web search (feature) | **Tavily** |
| Voice / ASR (feature) | **DashScope** (Qwen), **pydub** |

The backend loads environment variables from the **`.env`** file at the **monorepo root** (see `backend/main.py`).

### DevOps / tooling

- **Docker Compose** for containerized runs (if you use the compose setup in this repo).
- **ESLint** + **typescript-eslint** on the frontend.

---

## Repository layout

```
bms-insight-forge/
├── backend/           # FastAPI app (main:app), routers, generation, fill engine, modules
├── insight-forge-web/ # Vite + React SPA
├── .env.example       # Template for all env vars (copy to .env)
└── README.md          # This file
```

---

## Microsoft Entra ID (Azure AD)

Authentication is **optional** and controlled by environment variables. When enabled:

1. The **SPA** signs users in with **MSAL** and obtains an **access token** for your API.
2. The **browser** sends `Authorization: Bearer <access_token>` on API calls (Axios and the voice streaming `fetch` path).
3. The **API** validates the JWT (signature via Entra JWKS, plus `iss`, `aud`, `exp`) before running protected routes.

Public paths (no token required when `AUTH_ENABLED=true`): `GET /health`, OpenAPI/docs routes, and CORS **OPTIONS** preflight.

Stub values in **`.env.example`** are placeholders only. **End-to-end login requires real app registrations** and shareable settings from the team that manages Entra ID.

### What to provide to the team that manages Entra ID

Send them a short design summary so they can create or extend the right **app registrations**:

1. **Application shape**
   - **Single-page application (SPA)** built with React/Vite, using **MSAL** with the **authorization code flow + PKCE** (standard for public SPA clients; no client secret in the browser).
   - **Separate REST API** (FastAPI) that **only validates bearer access tokens**; the API does not perform the interactive login itself.

2. **SPA (front-end) registration**
   - Ask for a dedicated **application (client) ID** for this SPA (or confirmation of which existing registration to use).
   - List every **redirect URI** they must register. These must match **exactly** (scheme, host, port, path, no trailing slash unless you use it). Examples you might need:
     - Local: `http://localhost:5173` (or whichever port Vite uses in your setup)
     - Staging / production: full origins of your hosted UI (e.g. `https://app.example.com`)
   - Confirm **implicit flow** is **not** required; MSAL v2+ uses **PKCE** instead.

3. **API registration**
   - Ask them to expose this FastAPI service as a **protected API** in Entra (with an **Application ID URI**, e.g. `api://<api-app-id>`).
   - Ask for at least one **application permission / delegated scope** that the SPA can request (e.g. `access_as_user` or `.default`, depending on their standard).
   - Clarify whether the **access token `aud` claim** will be the Application ID URI, the API’s client ID, or another value — your backend **`ENTRA_API_AUDIENCE`** must match what appears in real tokens.

4. **Who can sign in**
   - **Single-tenant** (only your organization) vs **multi-tenant** vs **B2B guests** — this affects authority URLs and issuer validation. The current backend expects the tenant’s **v2** issuer pattern: `https://login.microsoftonline.com/<tenant-id>/v2.0`.

5. **Environments**
   - Whether **dev / staging / prod** each get separate registrations or the same app with multiple redirect URIs (follow their governance).

6. **Optional future needs (if relevant)**
   - **App roles**, **groups**, or **custom claims** you might need later for authorization inside the API.

### What to get back from them (and how to map it to `.env`)

Use the values they give you in your **root `.env`** (same file the backend and Vite both read, with `VITE_*` for the SPA).

| You need from them | Purpose | Your environment variable(s) |
|--------------------|---------|------------------------------|
| **Directory (tenant) ID** | Authority, issuer, and JWKS URL for token validation and MSAL | `ENTRA_TENANT_ID`, `VITE_ENTRA_TENANT_ID` (same UUID in both) |
| **SPA client ID** | MSAL `clientId` | `VITE_ENTRA_CLIENT_ID` |
| **API Application ID URI** and/or **expected `aud` value** | Must match the **`aud`** claim on access tokens your API receives | `ENTRA_API_AUDIENCE` (comma-separated if they confirm multiple valid audiences) |
| **Scope the SPA should request** (full string) | Used in `acquireTokenSilent` / login | `VITE_ENTRA_API_SCOPE` (e.g. `api://<api-app-id>/access_as_user`) |
| **Written list of registered redirect URIs** | Sanity check against your deployed URLs | (no env key — compare to `window.location.origin` / local Vite URL) |

Then enable integration:

- Set **`AUTH_ENABLED=true`** on the API.
- Set **`VITE_ENTRA_AUTH_ENABLED=true`** on the SPA.

If the flags are **false**, MSAL is not initialized and the API does not enforce JWTs — suitable for local development without Entra.

### Verifying local development

- With **real** registrations and **`http://localhost:5173`** (or your dev origin) registered as a redirect URI, you can test the full flow locally.
- With **`AUTH_ENABLED=true`** but no valid token, the API should respond with **401** on protected routes — useful to confirm middleware wiring.

---

## Quick start

1. Copy **`.env.example`** to **`.env`** and set your LLM and optional keys (e.g. `OPENAI_API_KEY`).
2. Run the backend with Docker Compose:
   ```bash
   docker compose up --build
   ```
3. In another terminal, run the web UI (default UI: [http://localhost:5173](http://localhost:5173); set `VITE_BACKEND_URL` if the API is not at `http://localhost:8001`):
   ```bash
   cd insight-forge-web && npm install && npm run dev
   ```

---

## Development (local)

1. Install backend dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

2. Run the backend (Terminal 1), from the `backend` directory with `PYTHONPATH` set so imports resolve:
Or use your project’s `run_backend.ps1` if present.

   ```bash
   cd backend && PYTHONPATH=. python -m uvicorn main:app --reload --port 8001
   ```

3. Run the React app (Terminal 2):
   ```bash
   cd insight-forge-web && npm install && npm run dev
   ```

4. Open the URL printed by Vite (typically `http://localhost:5173`).

5. Exposing the API from a VM (example):
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8001
   ```

For more detail on the Vite + React template defaults, see [`insight-forge-web/README.md`](insight-forge-web/README.md).
