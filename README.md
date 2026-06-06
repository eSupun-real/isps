# ISPS Port Security Management System
## Hambantota International Port — Sri Lanka

---

## Architecture Overview

```
isps-system/
├── server/
│   ├── app.py          ← Flask REST API (auth, vessels, docs, analysis, emails)
│   ├── db.py           ← SQLite schema + seeder
│   └── ocr_extract.py  ← Local OCR pipeline (pdfminer → Tesseract fallback)
├── client/
│   └── index.html      ← Single-page frontend (vanilla JS, no framework)
├── uploads/            ← Uploaded document files (created at runtime)
├── isps_hbt.db         ← SQLite database (created at runtime)
├── config.json         ← API keys (created via UI, never committed)
├── .env.example        ← Environment variable template
└── README.md
```

### Key Design Decisions

**OCR-first, LLM-last:**
1. Agent uploads documents → server runs local Tesseract OCR (pdfminer for digital PDFs, Tesseract for scanned)
2. Only the extracted *text* is sent to the LLM — never the binary files
3. LLM is called **once per vessel call** by ISPS Office staff, not on every upload
4. This minimises LLM costs significantly

**Local OCR pipeline:**
- Digital PDFs → `pdfminer.six` (fast, free, no API)
- Scanned/image PDFs → `pdf2image` + `pytesseract` (Tesseract 5.x, local)
- DOCX → `python-docx`
- EML email files → Python `email` stdlib

**Multi-LLM support:**
- Anthropic Claude Haiku (cheapest, default)
- OpenAI GPT-4o-mini
- OpenRouter (any model)
- Switch per-analysis from the dropdown

---

## Setup

### 1. System Requirements

- Python 3.10+
- Tesseract OCR 5.x (`apt install tesseract-ocr poppler-utils`)
- pip packages (install once):

```bash
pip3 install flask flask-cors flask-jwt-extended \
             pytesseract pdf2image pdfminer.six \
             python-docx bcrypt python-dotenv \
             --break-system-packages
```

### 2. Initialise the Database

```bash
cd isps-system
python3 server/db.py
```

This creates `isps_hbt.db` and seeds 4 default accounts.

### 3. Configure API Keys

Copy `.env.example` to `.env` and add your keys, **or** set them via the Configuration page in the UI after first login.

### 4. Run the Server

```bash
python3 server/app.py
```

Open **http://localhost:5050** in your browser.

For production, run behind Nginx with gunicorn:
```bash
pip3 install gunicorn --break-system-packages
gunicorn -w 2 -b 0.0.0.0:5050 server.app:app
```

---

## User Roles & Workflow

### Role: Agent (`agent_mol`, `agent_windsor`)
1. Log in → **Submit Documents** page
2. Fill in vessel particulars (name, IMO, ETA, flag, master, etc.)
3. Upload security documents to the labelled slots
4. Click **Submit** — OCR runs locally in the background
5. Track status on the **Vessel Calls** page

### Role: ISPS Office (`isps_office`)
1. Log in → **Review Documents** page
2. Select a vessel call → view OCR'd document contents + document status
3. Click **Run AI Analysis** (select LLM provider) → compliance check runs
4. Review flags and per-document discrepancy findings
5. Edit discrepancy details and corrective actions manually if needed
6. Click **Forward for Clearance** when satisfied

### Role: ISPS Officer / PFSO (`pfso_hbt`)
1. Log in → **No-Objection Emails** page
2. Select a cleared vessel → review AI-drafted emails
3. Edit email subject and body as needed (full editable textarea)
4. **Save Draft** at any time
5. Click **Send to Port Authority** or **Send to Agent** — opens mail client
6. Sending is logged with timestamp in the database

---

## Database Schema (SQLite → Supabase-ready)

### `vessel_calls`
| Column | Description |
|--------|-------------|
| voyage_ref | Auto-generated reference (e.g. HBT-20260530-A3F2C1) |
| vessel_name, imo_number, flag_state, vessel_type | Vessel identity |
| expected_arrival, departure | Schedule |
| status | `pending → documents_submitted → under_review → discrepancies_raised → cleared → no_objection_issued` |
| created_by | FK to users |

### `vessel_documents`
One row per vessel call. For each of 13 document types, there are **8 columns**:

| Column pattern | Description |
|----------------|-------------|
| `doc_{type}_path` | File path on disk |
| `doc_{type}_text` | OCR-extracted text |
| `doc_{type}_fields` | JSON of AI-extracted structured fields |
| `doc_{type}_received` | 0/1 boolean |
| `doc_{type}_discrepancy` | 0/1 flag |
| `doc_{type}_disc_detail` | Discrepancy description |
| `doc_{type}_corrective` | Corrective action required |
| `doc_{type}_verified` | 0/1 ISPS office verified |

Document types: `pans, issc, csr, dos, crew_list, armed_guards, isps_checklist, pi_certificate, hull_machinery, fal6, fal7, ship_particulars, other`

### `no_objections`
Stores both email drafts, sent status, timestamps.

### `custom_rules`
ISPS Officer's custom compliance rules — applied to every AI analysis.

### `activity_log`
Full audit trail: who did what, when, on which vessel call.

---

## Migrating to Supabase

The schema is Postgres-compatible. Steps:
1. Export SQLite → SQL: `python3 -c "import sqlite3,sys; ..."`
2. Run schema in Supabase SQL editor
3. Replace `get_db()` in `app.py` with `psycopg2` connection using `DATABASE_URL` env var
4. Upload files to Supabase Storage instead of local `uploads/` directory

---

## Default Accounts

| Username | Password | Role |
|----------|----------|------|
| `pfso_hbt` | `isps1234` | ISPS Officer (PFSO) — full access |
| `isps_office` | `office1234` | ISPS Office — review & analyse |
| `agent_mol` | `agent1234` | MOL Logistics Lanka |
| `agent_windsor` | `agent1234` | Windsor Reef Shipping |

**Change all passwords before deploying to production.**

---

## Documents Covered

| Document | Slot |
|----------|------|
| Pre-Arrival Notification of Security (PANS) | `pans` |
| International Ship Security Certificate (ISSC) | `issc` |
| Continuous Synopsis Record (CSR) | `csr` |
| Declaration of Security (DoS) | `dos` |
| IMO Crew List (FAL Form 5) | `crew_list` |
| Passenger List (FAL Form 6) | `fal6` |
| Dangerous Goods (FAL Form 7) | `fal7` |
| Declaration of Armed Guards | `armed_guards` |
| ISPS Navy Checklist | `isps_checklist` |
| P&I Certificate of Entry | `pi_certificate` |
| Hull & Machinery Certificate | `hull_machinery` |
| Ship Particulars | `ship_particulars` |
| Other / miscellaneous | `other` |

---

## ISPS Code Checks (always applied)

1. ISSC valid and not expired
2. CSR present and consistent with ISSC
3. Security level declared (Level 1)
4. Declaration of Security signed by both parties
5. No armed guards or weapons onboard
6. No dangerous goods declared
7. Ship Security Plan onboard and approved
8. Crew list complete (FAL Form 5)
9. No security incidents in last 10 port calls
10. PANS fully completed and signed

Plus any **Custom Rules** added by the ISPS Officer.
