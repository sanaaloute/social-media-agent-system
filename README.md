# H24 Social Media Agent

A multi-agent (LangGraph) system for multimodal social-media content generation and cross-platform publishing. It researches, plans, writes, illustrates, and critiques posts, then publishes them via official platform APIs or Playwright browser automation — with a mandatory human-in-the-loop approval step before anything is published.

## Architecture

- **User interaction** — FastAPI review panel (`/panel`) + REST API (`/api/...`); every post requires explicit human approval.
- **LangGraph orchestration** — a Supervisor agent routes work through specialized agents: Research, Planner, Writer, Image, Video, and Critic.
- **Publisher adapters** — official APIs for Facebook, Instagram, LinkedIn, YouTube, Twitter/X, and TikTok; Playwright browser automation for X and TikTok.
- **Infrastructure** — PostgreSQL (state, credentials, audit), Redis (cache, rate limits, broker), Celery (task queue; eager mode for local dev).

## Project layout

```
├── src/
│   ├── agents/          # LangGraph agents: supervisor, researcher, planner,
│   │                    #   writer, image, video, critic (+ providers, state, graph)
│   ├── api/             # FastAPI app + review panel (src.api.main:app)
│   ├── core/            # config, database engine, SQLModel models, redis
│   ├── publishers/      # API adapters + Playwright browser adapters
│   ├── utils/           # crypto, rate limiter, token manager, browser utils
│   └── workers/         # Celery app + tasks (src.workers.celery_app)
├── alembic/             # migration environment (no revisions yet — see Migrations)
├── browser_profiles/    # persistent Playwright profiles (stay local, git-ignored)
├── media_cache/         # generated media cache
├── docs/                # setup guides
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Quickstart — local (Windows / macOS / Linux)

```bash
python -m venv .venv
# Windows:            .venv\Scripts\activate
# macOS / Linux:      source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # needed for browser automation
cp .env.example .env
uvicorn src.api.main:app --reload
```

Open `http://localhost:8000/panel` for the review panel.

The default configuration is fully local — SQLite database, eager (in-process) queue, mock generation providers, and dry-run publishing — so the entire generate → review → publish loop works with zero credentials.

## Quickstart — Docker

Set `DB_PASSWORD` and `ENCRYPTION_KEY` in `.env` first. Generate the key with:

```bash
python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Then:

```bash
docker compose up --build
```

On this machine Docker runs inside WSL, so from Windows use:

```bash
wsl -e docker compose -f /mnt/e/H24-SocialMedia/docker-compose.yml up --build
```

This starts Postgres, Redis, the API (`:8000`), a Celery worker, and Celery beat. Browser profiles and media cache are bind-mounted from the project directory.

## Typical flow

1. `POST /api/tasks` with a topic/brief.
2. Agents research, draft, and generate media for the post (per-platform assets).
3. The content lands in the approval queue. Drafts carry a schedule from the planner (or from the task's `scheduled_at`).
4. A reviewer approves (or rejects/edits) it in the panel at `/panel`.
5. Approved content publishes at its scheduled time — immediately when no schedule is set, otherwise when the beat dispatcher (`dispatch_due`, every 60s in celery mode) picks it up. Publishing is simulated while `DRY_RUN=true`, live once credentials are configured and `DRY_RUN=false`.

## Configuration

All values are read from environment variables / `.env` (see `.env.example`). The most common ones — `DRY_RUN`, `MAX_POSTS_PER_ACCOUNT_PER_DAY`, and the three generation providers — can also be changed at runtime from the settings page at `/panel/settings.html` (stored as DB overrides, effective immediately, audited).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./dev.db` | SQLAlchemy URL; Postgres in compose |
| `REDIS_URL` | *(empty)* | Cache / rate limits / Celery broker; in-memory fallback when unset |
| `QUEUE_MODE` | `eager` | `eager` = run tasks inline; `celery` = real queue |
| `DRY_RUN` | `true` | Publishers simulate success instead of calling live APIs |
| `LLM_PROVIDER` / `IMAGE_PROVIDER` / `VIDEO_PROVIDER` | `mock` | Generation backends (`claude`/`openai`/`ollama`, `dalle`/`stable_diffusion`, `falai`/`kling`) |
| `ENCRYPTION_KEY` | *(empty)* | AES-256 key (base64url-encoded 32 bytes) for stored platform credentials |
| `MAX_POSTS_PER_ACCOUNT_PER_DAY` | `10` | Per-account daily posting cap, enforced by all adapters |

Platform API credentials (`META_APP_ID`, `LINKEDIN_CLIENT_ID`, etc.) are optional — everything runs in dry-run without them. See `docs/setup.md` to obtain them.

## Testing

```bash
pytest
```

## Migrations

Local dev uses `SQLModel.metadata.create_all` via `init_db()` on startup — no migrations needed. For real schema migrations:

```bash
alembic revision --autogenerate -m "init"   # generate a revision from the models
alembic upgrade head                        # apply migrations
```

`alembic/env.py` reads the database URL from the same settings as the app, so no extra configuration is required.

## ⚠ Compliance

Browser automation may violate platform Terms of Service. Use it only with accounts you own, and get legal review before any production deployment. Browser profiles under `browser_profiles/` stay on the local machine and are never committed or uploaded. Publishing is dry-run by default, and every post requires human approval before anything goes out.
