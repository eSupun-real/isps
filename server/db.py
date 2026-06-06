"""
db.py — SQLite schema and helpers for ISPS HBT Port Security System
Tables: users, vessels, documents, discrepancies, corrective_actions, no_objections, custom_rules
"""

import sqlite3
import os
import hashlib
import json
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "./isps_hbt.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ── Users ─────────────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    UNIQUE NOT NULL,
        password_hash TEXT  NOT NULL,
        role        TEXT    NOT NULL CHECK(role IN ('isps_officer','isps_office','agent')),
        full_name   TEXT,
        email       TEXT,
        phone       TEXT,
        company     TEXT,
        created_at  TEXT    DEFAULT (datetime('now')),
        is_active   INTEGER DEFAULT 1
    )""")

    # ── Vessels / Vessel calls ────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS vessel_calls (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        voyage_ref      TEXT    UNIQUE NOT NULL,
        vessel_name     TEXT    NOT NULL,
        imo_number      TEXT,
        flag_state      TEXT,
        vessel_type     TEXT,
        gross_tonnage   TEXT,
        master_name     TEXT,
        company_name    TEXT,
        agent_name      TEXT,
        agent_email     TEXT,
        agent_phone     TEXT,
        expected_arrival TEXT,
        actual_arrival  TEXT,
        departure       TEXT,
        purpose         TEXT,
        security_level  TEXT    DEFAULT 'LEVEL 1',
        berth           TEXT,
        latitude        TEXT,
        longitude       TEXT,
        status          TEXT    DEFAULT 'pending'
                            CHECK(status IN ('pending','documents_submitted','under_review',
                                             'discrepancies_raised','documents_corrected',
                                             'cleared','no_objection_issued','rejected')),
        created_by      INTEGER REFERENCES users(id),
        created_at      TEXT    DEFAULT (datetime('now')),
        updated_at      TEXT    DEFAULT (datetime('now'))
    )""")

    # Ensure latitude and longitude columns exist in case table was already created
    try:
        c.execute("ALTER TABLE vessel_calls ADD COLUMN latitude TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE vessel_calls ADD COLUMN longitude TEXT")
    except sqlite3.OperationalError:
        pass

    # ── Documents — one row per document type per vessel call ─────────────────
    # Each doc type has: file stored path, extracted text, LLM-extracted fields,
    # discrepancy flag, discrepancy detail, corrective action, corrected file path
    doc_types = [
        "pans", "issc", "csr", "dos", "crew_list",
        "armed_guards", "isps_checklist",
        "pi_certificate", "hull_machinery", "fal6", "fal7",
        "ship_particulars", "other"
    ]

    cols = []
    for dt in doc_types:
        cols.append(f"doc_{dt}_path          TEXT")
        cols.append(f"doc_{dt}_text          TEXT")
        cols.append(f"doc_{dt}_fields        TEXT")   # JSON extracted fields
        cols.append(f"doc_{dt}_received      INTEGER DEFAULT 0")
        cols.append(f"doc_{dt}_discrepancy   INTEGER DEFAULT 0")  # 0=ok,1=issue
        cols.append(f"doc_{dt}_disc_detail   TEXT")   # what is wrong
        cols.append(f"doc_{dt}_corrective    TEXT")   # corrective action text
        cols.append(f"doc_{dt}_corrected_path TEXT")  # re-submitted corrected file
        cols.append(f"doc_{dt}_verified      INTEGER DEFAULT 0")  # 1=office verified

    c.execute(f"""
    CREATE TABLE IF NOT EXISTS vessel_documents (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id         INTEGER NOT NULL REFERENCES vessel_calls(id) ON DELETE CASCADE,
        submitted_by    INTEGER REFERENCES users(id),
        submitted_at    TEXT    DEFAULT (datetime('now')),
        {", ".join(cols)},
        ocr_status      TEXT    DEFAULT 'pending',
        llm_status      TEXT    DEFAULT 'pending',
        overall_result  TEXT,      -- pass/warn/fail
        compliance_json TEXT,      -- full LLM JSON result
        updated_at      TEXT    DEFAULT (datetime('now'))
    )""")

    # ── No Objection records ──────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS no_objections (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id         INTEGER NOT NULL REFERENCES vessel_calls(id),
        issued_by       INTEGER REFERENCES users(id),
        issued_at       TEXT    DEFAULT (datetime('now')),
        email_port_subject TEXT,
        email_port_body    TEXT,
        email_port_sent    INTEGER DEFAULT 0,
        email_port_sent_at TEXT,
        email_agent_subject TEXT,
        email_agent_body    TEXT,
        email_agent_sent    INTEGER DEFAULT 0,
        email_agent_sent_at TEXT,
        notes           TEXT
    )""")

    # ── Custom rules ──────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS custom_rules (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        description TEXT NOT NULL,
        severity    TEXT DEFAULT 'advisory' CHECK(severity IN ('mandatory','advisory')),
        category    TEXT DEFAULT 'other',
        created_by  INTEGER REFERENCES users(id),
        created_at  TEXT DEFAULT (datetime('now')),
        is_active   INTEGER DEFAULT 1
    )""")

    # ── Activity log ─────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id     INTEGER REFERENCES vessel_calls(id),
        user_id     INTEGER REFERENCES users(id),
        action      TEXT NOT NULL,
        detail      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""")

    conn.commit()

    # ── Seed default users if none exist ─────────────────────────────────────
    import bcrypt as _bcrypt_check
    existing = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing == 0:
        import bcrypt
        users = [
            ("pfso_hbt",    "isps1234",   "isps_officer", "PFSO Hambantota",        "pfsohambantota@navy.lk",   "011 3070312", "Sri Lanka Navy"),
            ("isps_office", "office1234", "isps_office",  "ISPS Office HBT",        "pfsohambantota@gmail.com", "047 2258880", "Sri Lanka Navy"),
            ("agent_mol",   "agent1234",  "agent",        "MOL Logistics Lanka",    "sajiv.madasamy@molgroup.com","011 2304721","MOL Logistics Lanka (Pvt) Ltd"),
            ("agent_windsor","agent1234", "agent",        "Windsor Reef Shipping",  "ops@windsorreef.lk",       "011 2345678", "Windsor Reef Shipping"),
        ]
        for uname, pwd, role, fname, email, phone, company in users:
            h = bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()
            c.execute("INSERT INTO users(username,password_hash,role,full_name,email,phone,company) VALUES(?,?,?,?,?,?,?)",
                      (uname, h, role, fname, email, phone, company))
        conn.commit()
        print("[OK] Default users seeded")

    print(f"[OK] Database initialised at {DB_PATH}")
    conn.close()

if __name__ == "__main__":
    try:
        import bcrypt
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "bcrypt", "--break-system-packages"])
        import bcrypt
    init_db()
