# ISPS HBT Port Security System — Development Plan

## Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python Flask (monolithic, `server/app.py` ~1536 lines) |
| **Frontend** | Vanilla JS + Vite (SPA, `client_vite/`) |
| **Database** | SQLite (`uploads/isps_hbt.db`) |
| **OCR** | Local Tesseract pipeline (`server/ocr_extract.py`) |
| **LLM** | Multi-provider: Anthropic Claude / OpenAI GPT / OpenRouter |
| **Auth** | JWT (`flask-jwt-extended`) |
| **Hosting** | Docker -> Render (gunicorn) |
| **Live tracking** | aisstream.io WebSocket API |

The app is a Port Security Compliance System for Hambantota International Port,
Sri Lanka. It handles the full workflow: agents submit vessel docs -> OCR extracts
text -> LLM checks ISPS compliance -> officer issues no-objection emails.

---

## Current Pain Points / Gaps

1. **Conflicting backends** — Root `package.json` points to `server/index.js`
   (Node/Express), but the real backend is `server/app.py` (Python/Flask).
2. **Old `client/` directory** vs `client_vite/` — legacy code to clean up.
3. **Email sending is fake** — Uses `mailto:` links (opens local mail client).
   No SMTP integration. Emails are only marked as "sent" in the DB.
4. **API keys in plaintext** — `config.json` contains real-looking keys
   committed to the repo.
5. **No tests** — Zero test files found.
6. **No structured logging** — Just `print()` statements everywhere.
7. **SQLite won't scale** — No concurrency, no persistence guarantees.
8. **Security** — `CORS(origins="*")`, weak default passwords, hardcoded JWT
   secret fallback.

---

## Phase 1 — Cleanup & Safety (1-2 days)

- [ ] Remove dead `server/index.js` and old `client/` directory
- [ ] Rotate any exposed API keys immediately
- [ ] Move secrets from `config.json` to `.env` / environment variables only
- [ ] Set proper JWT secret in production
- [ ] Remove `config.json` from version control (add to `.gitignore`)

---

## Phase 2 — Foundation Hardening (3-5 days)

- [ ] Add tests (pytest for API, vitest for frontend)
- [ ] Structured logging (replace `print()` with Python `logging` module)
- [ ] Tighten CORS to specific origins

---

## Phase 3 — Production Readiness (1-2 weeks)

- [ ] Migrate DB from SQLite to PostgreSQL / Supabase
- [ ] File storage — move from local `uploads/` to S3-compatible storage
- [ ] OCR improvement — implement dots.mocr (VLM sidecar) for better accuracy
- [ ] CI/CD — add GitHub Actions for test + lint on PR

---

## Phase 4 — Polish (as needed)

- [ ] Extract CSS from `index.html` into proper stylesheet
- [ ] Add loading states / error boundaries on all pages
- [ ] Paginate vessel lists
- [ ] Add webhook or polling for document upload progress to agent
- [ ] Role-based UI refinement
- [ ] Session management (token refresh)
