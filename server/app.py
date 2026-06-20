"""
app.py — ISPS HBT Port Security Management System — Flask Backend
"""

import os
import sys
import json
import base64
import subprocess
import uuid
import zipfile
import tempfile
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
import bcrypt
import sqlite3

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
PROJECT_DIR = BASE_DIR.parent
# Default DB to the persistent uploads disk on Render; falls back to project root locally
DB_PATH    = os.environ.get("DB_PATH", str(PROJECT_DIR / "uploads" / "isps_hbt.db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(PROJECT_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

JWT_SECRET = os.environ.get("JWT_SECRET", "isps-hbt-secret-change-in-production-2024")

app = Flask(__name__, static_folder="../client", static_url_path="")
CORS(app, origins="*", supports_credentials=True)
app.config["JWT_SECRET_KEY"] = JWT_SECRET
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
jwt = JWTManager(app)

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def row_to_dict(row):
    if row is None: return None
    return dict(row)

def rows_to_list(rows):
    return [dict(r) for r in rows]

def log_action(conn, call_id, user_id, action, detail=""):
    conn.execute(
        "INSERT INTO activity_log(call_id,user_id,action,detail) VALUES(?,?,?,?)",
        (call_id, user_id, action, detail)
    )

def log_llm_call(conn, call_id, user_id, provider, model, prompt, response, error, duration_ms, status):
    conn.execute(
        "INSERT INTO llm_logs(call_id,user_id,provider,model,prompt,response,error,duration_ms,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (call_id, user_id, provider, model, prompt, response, error, duration_ms, status)
    )

def get_llm_model(provider):
    key = f"{provider.upper()}_MODEL"
    model = os.environ.get(key, "")
    if not model:
        defaults = {
            "anthropic": "claude-haiku-4-5-20251001",
            "openai": "gpt-4o-mini",
            "openrouter": "anthropic/claude-haiku-4-5"
        }
        model = defaults.get(provider, "")
    return model

def get_active_provider():
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text())
            return cfg.get("ACTIVE_PROVIDER", "anthropic")
    except:
        pass
    return "anthropic"

# ── Role decorator ────────────────────────────────────────────────────────────
def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            if claims.get("role") not in roles:
                return jsonify(error="Insufficient permissions"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def run_text_extract_api(filepath: str) -> str:
    url = os.environ.get("TEXT_EXTRACT_API_URL", "http://localhost:8000/api/v1/extract")
    try:
        # Use curl to avoid requests dependency issues
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", url, "-F", f"file=@{filepath}"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                return data.get("text", "") or data.get("markdown", "") or result.stdout
            except json.JSONDecodeError:
                return result.stdout
    except Exception as e:
        print(f"Error calling text-extract-api via curl: {e}")
    return ""

# ── LLM call (multi-provider) ─────────────────────────────────────────────────
def call_llm(prompt: str, system: str = "", provider: str = "anthropic") -> str:
    """Minimal LLM call — only used for compliance analysis, not OCR."""
    import urllib.request

    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
        if not model:
            model = "claude-haiku-4-5-20251001"
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
        body = json.dumps({
            "model": model,
            "max_tokens": 3000,
            "system": system,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"]

    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        if not model:
            model = "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        body = json.dumps({
            "model": model,
            "max_tokens": 3000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        }).encode()
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]

    elif provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        model = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5")
        if not model:
            model = "anthropic/claude-haiku-4-5"
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        body = json.dumps({
            "model": model,
            "max_tokens": 3000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ]
        }).encode()
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]

    return ""

# ── Build compliance prompt from extracted text ───────────────────────────────
def build_compliance_prompt(texts: dict, custom_rules: list, vessel_name: str) -> tuple:
    system = (
        "You are an ISPS compliance expert at Hambantota International Port, Sri Lanka. "
        "Analyse vessel security documents and return ONLY valid JSON — no markdown, no explanation."
    )

    # Document types for the JSON template
    doc_types = ["pans", "issc", "csr", "dos", "crew_list", "armed_guards", "isps_checklist",
                 "pi_certificate", "hull_machinery", "fal6", "fal7", "ship_particulars", "other"]

    # Concatenate all extracted texts (already done locally via OCR — no file sent to LLM)
    doc_sections = []
    for doc_type, text in texts.items():
        if text and text.strip():
            snippet = text[:3000]  # cap per doc to reduce tokens
            doc_sections.append(f"=== {doc_type.upper()} ===\n{snippet}")

    docs_text = "\n\n".join(doc_sections) if doc_sections else "No document text available."

    rules_text = ""
    if custom_rules:
        rules_text = "\n\nCUSTOM PORT RULES (mandatory rules must block clearance):\n"
        for i, r in enumerate(custom_rules, 1):
            rules_text += f"{i}. [{r['severity'].upper()}] {r['title']}: {r['description']}\n"

    # Build doc_findings JSON including ALL doc types (including 'other')
    doc_findings_json = ",\n    ".join([f'"{dt}": {{"status":"pass|fail|warn","issues":""}}' for dt in doc_types])
    
    prompt = f"""
Vessel: {vessel_name}

DOCUMENT EXTRACTS (OCR-processed locally):
{docs_text}
{rules_text}

Return ONLY this JSON:
{{
  "vessel": {{
    "name": "", "imo": "", "flag": "", "type": "", "gross_tonnage": "",
    "master": "", "company": "", "arrival": "", "departure": "",
    "purpose": "", "security_level": "", "issc_expiry": "", "issc_issuer": "",
    "agent_name": "", "agent_email": "", "agent_phone": ""
  }},
  "checks": [
    {{"id":"issc_valid","label":"ISSC valid and not expired","status":"pass|fail|warn","note":""}},
    {{"id":"csr_matches","label":"CSR present and matches ISSC","status":"pass|fail|warn","note":""}},
    {{"id":"security_level","label":"Security level declared (Level 1)","status":"pass|fail|warn","note":""}},
    {{"id":"dos_signed","label":"Declaration of Security signed by both parties","status":"pass|fail|warn","note":""}},
    {{"id":"no_arms","label":"No armed guards or weapons onboard","status":"pass|fail|warn","note":""}},
    {{"id":"no_dangerous_cargo","label":"No dangerous goods declared","status":"pass|fail|warn","note":""}},
    {{"id":"ssp_onboard","label":"Ship Security Plan onboard and approved","status":"pass|fail|warn","note":""}},
    {{"id":"crew_list","label":"Crew list complete (FAL Form 5)","status":"pass|fail|warn","note":""}},
    {{"id":"no_incidents","label":"No security incidents in last 10 port calls","status":"pass|fail|warn","note":""}},
    {{"id":"pans_complete","label":"PANS fully completed and signed","status":"pass|fail|warn","note":""}}
  ],
  "custom_checks": [{{"label":"","status":"pass|fail|warn","note":"","severity":"mandatory|advisory"}}],
  "flags": [{{"severity":"fail|warn","label":"","detail":""}}],
  "overall": "pass|fail|warn",
  "summary": "One sentence assessment.",
  "email_port": {{
    "to": "Port Authority / Harbour Master, Hambantota International Port",
    "subject": "",
    "body": ""
  }},
  "email_agent": {{
    "to": "",
    "subject": "",
    "body": ""
  }},
  "doc_findings": {{
    {doc_findings_json}
  }},
  "document_classification": {{
    "other": {{
      "identified_type": "pans|issc|csr|dos|crew_list|armed_guards|isps_checklist|pi_certificate|hull_machinery|fal6|fal7|ship_particulars|none",
      "confidence": 0.0-1.0,
      "reasoning": "Why this classification was made"
    }}
  }}
}}

Email signature for both emails:
Port Facility Security Officer (PFSO)
International Ships & Port Security Office
Hambantota International Port, Sri Lanka
Tel: 011 3070312 / 047 2258880
Email: pfsohambantota@gmail.com / pfsohambantota@navy.lk

If overall=pass → email_port is a No-Objection Certificate.
If overall=fail → email_port does NOT grant clearance; lists what is missing.
If overall=warn → email_port grants conditional clearance noting warnings.
flags[] must list EVERY discrepancy found.

If there are documents under 'other' that contain security-relevant content, classify them in document_classification.other[]. If identified as a known type, the text should be moved to that field in the database.
"""
    return system, prompt

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify(error="Username and password required"), 400

    db = get_db()
    user = row_to_dict(db.execute(
        "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
    ).fetchone())
    db.close()

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify(error="Invalid credentials"), 401

    token = create_access_token(
        identity=str(user["id"]),
        additional_claims={"role": user["role"], "username": user["username"], "name": user["full_name"]}
    )
    return jsonify(
        token=token,
        user={k: user[k] for k in ("id","username","role","full_name","email","company")}
    )

@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    db = get_db()
    user = row_to_dict(db.execute("SELECT id,username,role,full_name,email,phone,company FROM users WHERE id=?", (uid,)).fetchone())
    db.close()
    return jsonify(user)

@app.route("/api/auth/settings", methods=["PATCH"])
@roles_required("agent")
def update_settings():
    """Update agent's own profile (name, email, phone, company)"""
    uid = int(get_jwt_identity())
    data = request.json or {}
    full_name = data.get("full_name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    company = data.get("company", "").strip()
    
    if not full_name or not email:
        return jsonify(error="Name and email are required"), 400
    
    db = get_db()
    db.execute(
        "UPDATE users SET full_name=?, email=?, phone=?, company=? WHERE id=?",
        (full_name, email, phone, company, uid)
    )
    db.commit()
    
    user = row_to_dict(db.execute(
        "SELECT id,username,role,full_name,email,phone,company FROM users WHERE id=?", (uid,)
    ).fetchone())
    db.close()
    return jsonify(user)

# ═══════════════════════════════════════════════════════════════════════════════
# VESSEL CALLS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/vessels", methods=["GET"])
@jwt_required()
def list_vessels():
    claims = get_jwt()
    role = claims["role"]
    uid = int(get_jwt_identity())
    db = get_db()

    if role == "agent":
        # Agents see only their own submissions
        rows = rows_to_list(db.execute(
            "SELECT * FROM vessel_calls WHERE created_by=? ORDER BY expected_arrival DESC", (uid,)
        ).fetchall())
    else:
        rows = rows_to_list(db.execute(
            "SELECT * FROM vessel_calls ORDER BY expected_arrival DESC"
        ).fetchall())
    db.close()
    return jsonify(rows)

@app.route("/api/vessels", methods=["POST"])
@jwt_required()
def create_vessel():
    uid = int(get_jwt_identity())
    data = request.json or {}
    required = ["vessel_name", "expected_arrival"]
    for f in required:
        if not data.get(f):
            return jsonify(error=f"{f} is required"), 400

    voyage_ref = f"HBT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    db = get_db()
    cur = db.execute("""
        INSERT INTO vessel_calls (voyage_ref,vessel_name,imo_number,flag_state,vessel_type,
            gross_tonnage,master_name,company_name,agent_name,agent_email,agent_phone,
            expected_arrival,departure,purpose,security_level,berth,latitude,longitude,created_by)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (voyage_ref, data["vessel_name"], data.get("imo_number",""),
          data.get("flag_state",""), data.get("vessel_type",""), data.get("gross_tonnage",""),
          data.get("master_name",""), data.get("company_name",""), data.get("agent_name",""),
          data.get("agent_email",""), data.get("agent_phone",""), data["expected_arrival"],
          data.get("departure",""), data.get("purpose",""), data.get("security_level","LEVEL 1"),
          data.get("berth",""), data.get("latitude",""), data.get("longitude",""), uid))
    call_id = cur.lastrowid
    # Create empty document record
    db.execute("INSERT INTO vessel_documents(call_id, submitted_by) VALUES(?,?)", (call_id, uid))
    log_action(db, call_id, uid, "vessel_created", f"Voyage ref: {voyage_ref}")
    db.commit()
    db.close()
    return jsonify(voyage_ref=voyage_ref, call_id=call_id), 201

@app.route("/api/vessels/<int:call_id>", methods=["GET"])
@jwt_required()
def get_vessel(call_id):
    db = get_db()
    vessel = row_to_dict(db.execute("SELECT * FROM vessel_calls WHERE id=?", (call_id,)).fetchone())
    if not vessel:
        db.close()
        return jsonify(error="Not found"), 404
    docs = row_to_dict(db.execute("SELECT * FROM vessel_documents WHERE call_id=?", (call_id,)).fetchone())
    nobj = row_to_dict(db.execute("SELECT * FROM no_objections WHERE call_id=? ORDER BY issued_at DESC LIMIT 1", (call_id,)).fetchone())
    logs = rows_to_list(db.execute(
        "SELECT l.*,u.full_name FROM activity_log l LEFT JOIN users u ON l.user_id=u.id WHERE l.call_id=? ORDER BY l.created_at DESC",
        (call_id,)
    ).fetchall())
    db.close()
    return jsonify(vessel=vessel, documents=docs, no_objection=nobj, activity=logs)

@app.route("/api/vessels/<int:call_id>/status", methods=["PATCH"])
@roles_required("isps_officer","isps_office")
def update_status(call_id):
    uid = int(get_jwt_identity())
    data = request.json or {}
    status = data.get("status")
    if not status:
        return jsonify(error="status required"), 400
    db = get_db()
    db.execute("UPDATE vessel_calls SET status=?,updated_at=datetime('now') WHERE id=?", (status, call_id))
    log_action(db, call_id, uid, "status_updated", status)
    db.commit()
    db.close()
    return jsonify(ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT UPLOAD & OCR
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/vessels/<int:call_id>/documents", methods=["POST"])
@jwt_required()
def upload_documents(call_id):
    """
    Accepts JSON: { docs: [{ doc_type, filename, b64 }] }
    Saves files to disk. OCR is deferred to the analysis phase.
    """
    uid = int(get_jwt_identity())
    data = request.json or {}
    docs = data.get("docs", [])
    if not docs:
        return jsonify(error="No documents provided"), 400

    db = get_db()
    vessel = row_to_dict(db.execute("SELECT * FROM vessel_calls WHERE id=?", (call_id,)).fetchone())
    if not vessel:
        db.close()
        return jsonify(error="Vessel call not found"), 404

    # Ensure doc record exists
    doc_rec = row_to_dict(db.execute("SELECT * FROM vessel_documents WHERE call_id=?", (call_id,)).fetchone())
    if not doc_rec:
        db.execute("INSERT INTO vessel_documents(call_id,submitted_by) VALUES(?,?)", (call_id, uid))
        db.commit()

    results = {}
    for doc in docs:
        doc_type = doc.get("doc_type", "other").lower().replace(" ","_")
        filename  = doc.get("filename", "file.pdf")
        b64       = doc.get("b64", "")
        if not b64:
            continue

        # Save file to disk
        ext = Path(filename).suffix
        save_name = f"{call_id}_{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
        save_path = UPLOAD_DIR / save_name
        with open(save_path, "wb") as f:
            f.write(base64.b64decode(b64))

        # Update DB columns
        safe_type = doc_type if doc_type in [
            "pans","issc","csr","dos","crew_list","armed_guards","isps_checklist",
            "pi_certificate","hull_machinery","fal6","fal7","ship_particulars","other"
        ] else "other"

        db.execute(f"""
            UPDATE vessel_documents
            SET doc_{safe_type}_path=?,
                doc_{safe_type}_received=1,
                updated_at=datetime('now')
            WHERE call_id=?
        """, (str(save_path), call_id))

        results[doc_type] = {"saved": save_name}

    # Update vessel status
    db.execute("UPDATE vessel_calls SET status='documents_submitted',updated_at=datetime('now') WHERE id=?", (call_id,))
    log_action(db, call_id, uid, "documents_uploaded", json.dumps(list(results.keys())))
    db.commit()
    db.close()
    return jsonify(ok=True, upload_results=results)

# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE ANALYSIS (LLM — called explicitly by ISPS office)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/vessels/<int:call_id>/analyse", methods=["POST"])
@roles_required("isps_officer","isps_office")
def analyse_vessel(call_id):
    """
    Runs LLM compliance analysis on already-OCR'd text.
    LLM receives only extracted text, NOT the binary files → cost saving.
    """
    uid = int(get_jwt_identity())
    data = request.json or {}
    provider = data.get("provider", "") or get_active_provider()

    db = get_db()
    vessel = row_to_dict(db.execute("SELECT * FROM vessel_calls WHERE id=?", (call_id,)).fetchone())
    doc_rec = row_to_dict(db.execute("SELECT * FROM vessel_documents WHERE call_id=?", (call_id,)).fetchone())
    if not vessel or not doc_rec:
        db.close()
        return jsonify(error="Not found"), 404

    custom_rules = rows_to_list(db.execute(
        "SELECT title,description,severity,category FROM custom_rules WHERE is_active=1"
    ).fetchall())

    doc_types = ["pans","issc","csr","dos","crew_list","armed_guards","isps_checklist",
                 "pi_certificate","hull_machinery","fal6","fal7","ship_particulars","other"]

    # 1. OCR the PANS document first
    pans_path = doc_rec.get("doc_pans_path")
    pans_text = doc_rec.get("doc_pans_text") or ""
    if pans_path and not pans_text:
        pans_text = run_text_extract_api(pans_path)
        db.execute("UPDATE vessel_documents SET doc_pans_text=? WHERE call_id=?", (pans_text, call_id))
        db.commit()

    # 2. Ask LLM what documents are required based on PANS
    required_docs = doc_types # default to all
    if pans_text:
        req_prompt = f"Based on the following PANS document text, which of these document types are required for this vessel call? {doc_types}\n\nPANS Text:\n{pans_text[:4000]}\n\nReturn ONLY a JSON array of the required document types (e.g. [\"pans\", \"issc\"])."
        req_system = "You are an assistant that extracts required document types from a Pre-Arrival Notification (PANS)."
        try:
            req_raw = call_llm(req_prompt, req_system, provider)
            clean = req_raw.replace("```json","").replace("```","").strip()
            s = clean.find("["); e2 = clean.rfind("]")
            if s != -1 and e2 != -1:
                parsed_reqs = json.loads(clean[s:e2+1])
                required_docs = [d for d in parsed_reqs if d in doc_types]
                if "pans" not in required_docs:
                    required_docs.append("pans")
        except Exception as e:
            print("Failed to get required docs from LLM:", e)

    # 3. OCR the required documents
    texts = {}
    for dt in doc_types:
        if dt not in required_docs:
            continue
        path = doc_rec.get(f"doc_{dt}_path")
        text = doc_rec.get(f"doc_{dt}_text")
        if path and not text:
            text = run_text_extract_api(path)
            db.execute(f"UPDATE vessel_documents SET doc_{dt}_text=? WHERE call_id=?", (text, call_id))
            db.commit()
        if text and text.strip():
            texts[dt] = text

    system, prompt = build_compliance_prompt(texts, custom_rules, vessel["vessel_name"])
    model = get_llm_model(provider)

    import time
    start_ms = int(time.time() * 1000)
    raw = ""
    llm_error = None

    try:
        raw = call_llm(prompt, system, provider)
    except Exception as e:
        llm_error = str(e)
        duration_ms = int(time.time() * 1000) - start_ms
        log_llm_call(db, call_id, uid, provider, model, prompt[:3000], "", llm_error, duration_ms, "error")
        db.commit()
        db.close()
        return jsonify(error=f"LLM error: {llm_error}"), 500

    duration_ms = int(time.time() * 1000) - start_ms

    # Check if LLM returned valid response
    if not raw or not raw.strip():
        llm_error = "Empty response"
        log_llm_call(db, call_id, uid, provider, model, prompt[:3000], "", llm_error, duration_ms, "error")
        db.commit()
        db.close()
        return jsonify(error="LLM returned empty response. Check API key and quota."), 500

    # Parse JSON from LLM response
    parsed = None
    try:
        clean = raw.replace("```json","").replace("```","").strip()
        s = clean.index("{"); e2 = clean.rindex("}")
        parsed = json.loads(clean[s:e2+1])
    except Exception:
        log_llm_call(db, call_id, uid, provider, model, prompt[:3000], raw[:5000], "LLM returned invalid JSON", duration_ms, "parse_error")
        db.commit()
        db.close()
        return jsonify(error="LLM returned invalid JSON", raw=raw[:500] if raw else ""), 500

    # Log successful call
    log_llm_call(db, call_id, uid, provider, model, prompt[:3000], raw[:5000], None, duration_ms, "success")

    # Update vessel fields from LLM extraction
    v = parsed.get("vessel", {})
    update_fields = []
    update_vals = []
    field_map = {
        "imo_number":"imo","flag_state":"flag","vessel_type":"type",
        "gross_tonnage":"gross_tonnage","master_name":"master","company_name":"company",
        "agent_name":"agent_name","agent_email":"agent_email","agent_phone":"agent_phone",
        "departure":"departure","purpose":"purpose","security_level":"security_level"
    }
    for db_col, json_key in field_map.items():
        val = v.get(json_key,"")
        if val:
            update_fields.append(f"{db_col}=?")
            update_vals.append(val)
    if update_fields:
        update_vals.append(call_id)
        db.execute(f"UPDATE vessel_calls SET {','.join(update_fields)},updated_at=datetime('now') WHERE id=?", update_vals)

    # Update doc discrepancies per-document
    doc_findings = parsed.get("doc_findings", {})
    known_doc_types = ["pans","issc","csr","dos","crew_list","armed_guards","isps_checklist",
                      "pi_certificate","hull_machinery","fal6","fal7","ship_particulars"]
    for dt in known_doc_types:
        finding = doc_findings.get(dt, {})
        status = finding.get("status", "pass")
        issues = finding.get("issues", "")
        disc_flag = 1 if status in ("fail","warn") else 0
        db.execute(f"""
            UPDATE vessel_documents
            SET doc_{dt}_discrepancy=?, doc_{dt}_disc_detail=?
            WHERE call_id=?
        """, (disc_flag, issues, call_id))
    
    # Handle 'other' document classification and re-routing
    other_text = doc_rec.get("doc_other_text") or ""
    other_path = doc_rec.get("doc_other_path", "")
    if other_text.strip() and other_path:
        doc_classification = parsed.get("document_classification", {}).get("other", {})
        identified_type = doc_classification.get("identified_type", "none")
        confidence = float(doc_classification.get("confidence", 0))
        
        if identified_type and identified_type in known_doc_types and confidence > 0.5:
            # Get discrepancy info for the identified type
            other_finding = doc_findings.get(identified_type, {})
            other_status = other_finding.get("status", "pass")
            other_issues = other_finding.get("issues", "")
            other_disc_flag = 1 if other_status in ("fail","warn") else 0
            
            # Move 'other' text to the identified field
            db.execute(f"""
                UPDATE vessel_documents
                SET doc_{identified_type}_text=?,
                    doc_{identified_type}_received=1,
                    doc_{identified_type}_discrepancy=?,
                    doc_{identified_type}_disc_detail=?
                WHERE call_id=?
            """, (other_text, other_disc_flag, other_issues, call_id))
            
            # Clear the 'other' text field but keep the file path for reference
            db.execute("""
                UPDATE vessel_documents
                SET doc_other_text=''
                WHERE call_id=?
            """, (call_id,))

    # Save full compliance result
    overall = parsed.get("overall","pass")
    db.execute("""
        UPDATE vessel_documents
        SET compliance_json=?, overall_result=?, llm_status='done', updated_at=datetime('now')
        WHERE call_id=?
    """, (json.dumps(parsed), overall, call_id))

    new_status = "cleared" if overall == "pass" else "discrepancies_raised"
    db.execute("UPDATE vessel_calls SET status=?,updated_at=datetime('now') WHERE id=?", (new_status, call_id))

    # Pre-fill email drafts in no_objections table
    ep = parsed.get("email_port", {})
    ea = parsed.get("email_agent", {})
    existing_no = db.execute("SELECT id FROM no_objections WHERE call_id=?", (call_id,)).fetchone()
    if existing_no:
        db.execute("""
            UPDATE no_objections SET email_port_subject=?,email_port_body=?,
            email_agent_subject=?,email_agent_body=? WHERE call_id=?
        """, (ep.get("subject",""), ep.get("body",""), ea.get("subject",""), ea.get("body",""), call_id))
    else:
        db.execute("""
            INSERT INTO no_objections(call_id,issued_by,email_port_subject,email_port_body,email_agent_subject,email_agent_body)
            VALUES(?,?,?,?,?,?)
        """, (call_id, uid, ep.get("subject",""), ep.get("body",""), ea.get("subject",""), ea.get("body","")))

    log_action(db, call_id, uid, "compliance_analysed", f"Overall: {overall} | Provider: {provider}")
    db.commit()
    db.close()
    return jsonify(result=parsed, overall=overall)

# ═══════════════════════════════════════════════════════════════════════════════
# DISCREPANCIES & CORRECTIVE ACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/vessels/<int:call_id>/discrepancy", methods=["PATCH"])
@roles_required("isps_officer","isps_office")
def update_discrepancy(call_id):
    uid = int(get_jwt_identity())
    data = request.json or {}
    doc_type = data.get("doc_type","").lower().replace(" ","_")
    disc_detail = data.get("disc_detail","")
    corrective = data.get("corrective_action","")
    disc_flag = 1 if data.get("has_discrepancy", True) else 0

    db = get_db()
    db.execute(f"""
        UPDATE vessel_documents
        SET doc_{doc_type}_discrepancy=?,
            doc_{doc_type}_disc_detail=?,
            doc_{doc_type}_corrective=?,
            updated_at=datetime('now')
        WHERE call_id=?
    """, (disc_flag, disc_detail, corrective, call_id))
    db.execute("UPDATE vessel_calls SET status='discrepancies_raised',updated_at=datetime('now') WHERE id=?", (call_id,))
    log_action(db, call_id, uid, "discrepancy_updated", f"{doc_type}: {disc_detail[:80]}")
    db.commit()
    db.close()
    return jsonify(ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# NO OBJECTION
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/vessels/<int:call_id>/no-objection", methods=["GET"])
@jwt_required()
def get_no_objection(call_id):
    db = get_db()
    nobj = row_to_dict(db.execute(
        "SELECT * FROM no_objections WHERE call_id=? ORDER BY issued_at DESC LIMIT 1", (call_id,)
    ).fetchone())
    db.close()
    return jsonify(nobj)

@app.route("/api/vessels/<int:call_id>/no-objection", methods=["PUT"])
@roles_required("isps_officer")
def update_no_objection(call_id):
    uid = int(get_jwt_identity())
    data = request.json or {}
    db = get_db()
    existing = db.execute("SELECT id FROM no_objections WHERE call_id=?", (call_id,)).fetchone()
    if existing:
        db.execute("""
            UPDATE no_objections
            SET email_port_subject=?, email_port_body=?,
                email_agent_subject=?, email_agent_body=?, notes=?
            WHERE call_id=?
        """, (data.get("email_port_subject",""), data.get("email_port_body",""),
              data.get("email_agent_subject",""), data.get("email_agent_body",""),
              data.get("notes",""), call_id))
    else:
        db.execute("""
            INSERT INTO no_objections(call_id,issued_by,email_port_subject,email_port_body,email_agent_subject,email_agent_body,notes)
            VALUES(?,?,?,?,?,?,?)
        """, (call_id, uid, data.get("email_port_subject",""), data.get("email_port_body",""),
              data.get("email_agent_subject",""), data.get("email_agent_body",""), data.get("notes","")))
    db.commit()
    db.close()
    return jsonify(ok=True)

@app.route("/api/vessels/<int:call_id>/no-objection/send", methods=["POST"])
@roles_required("isps_officer")
def send_no_objection(call_id):
    uid = int(get_jwt_identity())
    data = request.json or {}
    target = data.get("target","port")  # "port" or "agent"
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if target == "port":
        db.execute("UPDATE no_objections SET email_port_sent=1,email_port_sent_at=? WHERE call_id=?", (now, call_id))
    else:
        db.execute("UPDATE no_objections SET email_agent_sent=1,email_agent_sent_at=? WHERE call_id=?", (now, call_id))

    db.execute("UPDATE vessel_calls SET status='no_objection_issued',updated_at=datetime('now') WHERE id=?", (call_id,))
    log_action(db, call_id, uid, "no_objection_sent", f"Target: {target}")
    db.commit()
    db.close()
    return jsonify(ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM RULES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/rules", methods=["GET"])
@jwt_required()
def get_rules():
    db = get_db()
    rules = rows_to_list(db.execute("SELECT * FROM custom_rules WHERE is_active=1 ORDER BY id DESC").fetchall())
    db.close()
    return jsonify(rules)

@app.route("/api/rules", methods=["POST"])
@roles_required("isps_officer","isps_office")
def add_rule():
    uid = int(get_jwt_identity())
    data = request.json or {}
    if not data.get("title") or not data.get("description"):
        return jsonify(error="title and description required"), 400
    db = get_db()
    db.execute("""
        INSERT INTO custom_rules(title,description,severity,category,created_by)
        VALUES(?,?,?,?,?)
    """, (data["title"], data["description"], data.get("severity","advisory"), data.get("category","other"), uid))
    db.commit()
    rules = rows_to_list(db.execute("SELECT * FROM custom_rules WHERE is_active=1 ORDER BY id DESC").fetchall())
    db.close()
    return jsonify(rules), 201

@app.route("/api/rules/<int:rule_id>", methods=["DELETE"])
@roles_required("isps_officer","isps_office")
def delete_rule(rule_id):
    db = get_db()
    db.execute("UPDATE custom_rules SET is_active=0 WHERE id=?", (rule_id,))
    db.commit()
    db.close()
    return jsonify(ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG (API keys — stored server-side only)
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = BASE_DIR / ".." / "config.json"

@app.route("/api/config", methods=["GET"])
@roles_required("isps_officer")
def get_config():
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
        # Mask only API keys (keys ending with _KEY)
        masked = {}
        for k, v in cfg.items():
            if k.upper().endswith("_KEY"):
                masked[k] = ("*" * 8 + v[-4:]) if v else ""
            else:
                masked[k] = v
        return jsonify(masked)
    except:
        return jsonify({})

@app.route("/api/config", methods=["POST"])
@roles_required("isps_officer")
def save_config():
    data = request.json or {}
    try:
        existing = {}
        if CONFIG_FILE.exists():
            existing = json.loads(CONFIG_FILE.read_text())
        # Only update keys that are not masked
        for k, v in data.items():
            if v is not None and not str(v).startswith("*"):
                existing[k] = v
            elif v == "":
                existing[k] = ""
        CONFIG_FILE.write_text(json.dumps(existing, indent=2))
        # Apply to env
        for k, v in existing.items():
            os.environ[k.upper()] = v
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/api/config/active-provider", methods=["GET"])
@roles_required("isps_officer", "isps_office")
def get_active_provider_endpoint():
    provider = get_active_provider()
    model = get_llm_model(provider)
    return jsonify(provider=provider, model=model)

# ═══════════════════════════════════════════════════════════════════════════════
# LLM LOGS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/llm-logs", methods=["GET"])
@roles_required("isps_officer")
def get_llm_logs():
    db = get_db()
    rows = rows_to_list(db.execute("""
        SELECT l.*, v.vessel_name, u.full_name as user_name
        FROM llm_logs l
        LEFT JOIN vessel_calls v ON l.call_id = v.id
        LEFT JOIN users u ON l.user_id = u.id
        ORDER BY l.created_at DESC
        LIMIT 200
    """).fetchall())
    db.close()
    return jsonify(rows)

# ── Fallback mock data and dynamic lookup for vessels ─────────────────────────
MOCK_VESSELS = {
    "9982990": {
        "vessel_name": "CELESTE ACE",
        "gross_tonnage": "73132",
        "vessel_type": "Pure Car Carrier",
        "flag_state": "Panama",
        "latitude": "6.1245",
        "longitude": "81.1243"
    },
    "9212266": {
        "vessel_name": "COSCO SHIPPING GEMINI",
        "gross_tonnage": "141823",
        "vessel_type": "Container Ship",
        "flag_state": "Hong Kong",
        "latitude": "5.9400",
        "longitude": "80.5000"
    },
    "9811000": {
        "vessel_name": "OCEAN PRINCESS",
        "gross_tonnage": "45000",
        "vessel_type": "Passenger Ship",
        "flag_state": "Bahamas",
        "latitude": "6.0500",
        "longitude": "81.2000"
    },
    "9112233": {
        "vessel_name": "HAMBANTOTA STAR",
        "gross_tonnage": "52000",
        "vessel_type": "Bulk Carrier",
        "flag_state": "Sri Lanka",
        "latitude": "6.1000",
        "longitude": "81.1500"
    }
}

def generate_fallback_vessel(imo):
    import hashlib
    h = hashlib.md5(str(imo).encode()).hexdigest()
    names = ["PACIFIC EXPLORER", "ATLANTIC SOVEREIGN", "NORDIC TRADER", "OCEAN SENTINEL", "STAR HORIZON", "SEA VOYAGER"]
    types = ["Bulk Carrier", "Crude Oil Tanker", "General Cargo Ship", "Container Ship", "LNG Carrier"]
    flags = ["Panama", "Liberia", "Marshall Islands", "Singapore", "Bahamas", "Malta"]
    
    idx = int(h[:4], 16)
    name = names[idx % len(names)] + f" {int(h[4:6], 16)}"
    vtype = types[idx % len(types)]
    flag = flags[idx % len(flags)]
    gt = str(20000 + (idx % 80) * 1000)
    
    lat = str(5.8 + (int(h[6:8], 16) % 50) * 0.01)
    lon = str(80.5 + (int(h[8:10], 16) % 100) * 0.01)
    
    return {
        "vessel_name": name,
        "gross_tonnage": gt,
        "vessel_type": vtype,
        "flag_state": flag,
        "latitude": lat,
        "longitude": lon
    }

async def query_aisstream_for_imo(api_key, target_imo):
    import asyncio
    import websockets
    uri = "wss://stream.aisstream.io/v0/stream"
    try:
        async with websockets.connect(uri, ping_interval=None, timeout=4) as websocket:
            subscribe_message = {
                "Apikey": api_key,
                "BoundingBoxes": [[[-90, -180], [90, 180]]],
                "FilterMessageTypes": ["ShipStaticData", "PositionReport"]
            }
            await websocket.send(json.dumps(subscribe_message))
            
            import time
            start_time = time.time()
            matched_static = None
            matched_position = None
            
            while time.time() - start_time < 3.0:
                try:
                    msg_json = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    msg = json.loads(msg_json)
                    msg_type = msg.get("MessageType")
                    metadata = msg.get("MetaData", {})
                    
                    if msg_type == "ShipStaticData":
                        static_data = msg.get("Message", {}).get("ShipStaticData", {})
                        imo = static_data.get("ImoNumber")
                        if str(imo) == str(target_imo):
                            matched_static = static_data
                            if metadata.get("latitude") and metadata.get("longitude"):
                                matched_position = {
                                    "latitude": str(metadata["latitude"]),
                                    "longitude": str(metadata["longitude"])
                                }
                            break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                    
            if matched_static:
                ship_type_code = matched_static.get("Type", 0)
                ship_type_str = "Cargo Vessel"
                if 70 <= ship_type_code <= 79:
                    ship_type_str = "Cargo Vessel"
                elif 80 <= ship_type_code <= 89:
                    ship_type_str = "Tanker"
                elif 60 <= ship_type_code <= 69:
                    ship_type_str = "Passenger Vessel"
                elif 30 <= ship_type_code <= 39:
                    ship_type_str = "Fishing Vessel"
                elif 50 <= ship_type_code <= 59:
                    ship_type_str = "Special Craft"
                
                dim = matched_static.get("Dimension", {})
                length = dim.get("A", 0) + dim.get("B", 0)
                width = dim.get("C", 0) + dim.get("D", 0)
                gt = "25000"
                if length > 0 and width > 0:
                    gt = str(int(length * width * 3.5))
                    
                mmsi_str = str(matched_static.get("UserID", ""))
                flag_state = "Unknown"
                if mmsi_str:
                    mid = mmsi_str[:3]
                    mid_map = {
                        "351": "Panama", "352": "Panama", "353": "Panama", "354": "Panama", "355": "Panama", "356": "Panama", "357": "Panama",
                        "370": "Panama", "371": "Panama", "372": "Panama", "373": "Panama", "374": "Panama",
                        "636": "Liberia", "538": "Marshall Islands", "563": "Singapore", "564": "Singapore", "565": "Singapore", "566": "Singapore",
                        "255": "Portugal", "248": "Malta", "232": "United Kingdom", "233": "United Kingdom", "234": "United Kingdom", "235": "United Kingdom",
                        "412": "China", "413": "China", "414": "China", "419": "India", "477": "Hong Kong",
                        "228": "France", "244": "Netherlands", "247": "Italy", "311": "Bahamas", "308": "Bahamas", "309": "Bahamas"
                    }
                    flag_state = mid_map.get(mid, "International Flag")

                return {
                    "vessel_name": matched_static.get("Name", "").strip(),
                    "gross_tonnage": gt,
                    "vessel_type": ship_type_str,
                    "flag_state": flag_state,
                    "latitude": matched_position.get("latitude") if matched_position else "6.1243",
                    "longitude": matched_position.get("longitude") if matched_position else "81.1243"
                }
    except Exception as e:
        print(f"AISStream query exception: {e}")
    return None

def lookup_vessel_by_imo(target_imo):
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except:
            pass
    api_key = config.get("AISTREAM_API_KEY") or os.environ.get("AISTREAM_API_KEY")
    if api_key:
        try:
            import asyncio
            res = asyncio.run(query_aisstream_for_imo(api_key, target_imo))
            if res:
                return res
        except Exception as e:
            print(f"Failed to query AISStream: {e}")
            
    if str(target_imo) in MOCK_VESSELS:
        return MOCK_VESSELS[str(target_imo)]
    return generate_fallback_vessel(target_imo)

def fetch_anthropic_models(api_key):
    import urllib.request
    if not api_key:
        return []
    url = "https://api.anthropic.com/v1/models"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return [m["id"] for m in data.get("data", [])]
    except Exception as e:
        print(f"Error fetching Anthropic models: {e}")
        return []

def fetch_openai_models(api_key):
    import urllib.request
    if not api_key:
        return []
    url = "https://api.openai.com/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return sorted([m["id"] for m in data.get("data", []) if "gpt" in m["id"] or "o1" in m["id"] or "o3" in m["id"]])
    except Exception as e:
        print(f"Error fetching OpenAI models: {e}")
        return []

def fetch_openrouter_models(api_key):
    import urllib.request
    url = "https://openrouter.ai/api/v1/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return sorted([m["id"] for m in data.get("data", [])])
    except Exception as e:
        print(f"Error fetching OpenRouter models: {e}")
        return []

@app.route("/api/config/models", methods=["GET"])
@roles_required("isps_officer")
def get_config_models():
    api_keys = {}
    if CONFIG_FILE.exists():
        try:
            api_keys = json.loads(CONFIG_FILE.read_text())
        except:
            pass
            
    anthropic_key = api_keys.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = api_keys.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    openrouter_key = api_keys.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
    
    anthropic_models = fetch_anthropic_models(anthropic_key)
    openai_models = fetch_openai_models(openai_key)
    openrouter_models = fetch_openrouter_models(openrouter_key)
    
    default_anthropic = ["claude-haiku-4-5-20251001", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"]
    default_openai = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "o1-mini", "o3-mini"]
    default_openrouter = ["anthropic/claude-haiku-4-5", "google/gemini-2.5-flash", "openai/gpt-4o-mini", "meta-llama/llama-3-8b-instruct"]
    
    res_anthropic = list(dict.fromkeys(default_anthropic + anthropic_models))
    res_openai = list(dict.fromkeys(default_openai + openai_models))
    res_openrouter = list(dict.fromkeys(default_openrouter + openrouter_models))
    
    return jsonify({
        "anthropic": res_anthropic,
        "openai": res_openai,
        "openrouter": res_openrouter
    })

@app.route("/api/vessels/lookup-imo/<imo>", methods=["GET"])
@jwt_required()
def lookup_imo(imo):
    try:
        data = lookup_vessel_by_imo(imo)
        return jsonify(data)
    except Exception as e:
        return jsonify(error=str(e)), 500

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k, v in cfg.items():
                os.environ.setdefault(k.upper(), v)
        except:
            pass

def ensure_db():
    """Initialize database schema and seed users if the DB doesn't exist yet."""
    try:
        from server.db import init_db
    except ImportError:
        try:
            from db import init_db
        except ImportError:
            print("[WARN] Could not import db.init_db — skipping auto-init")
            return
    try:
        init_db()
    except Exception as e:
        print(f"[WARN] DB init error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# THUMBNAILS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/api/documents/<path:filename>/thumbnail")
@jwt_required()
def get_document_thumbnail(filename):
    """Get thumbnail preview for a document."""
    doc_path = UPLOAD_DIR / filename
    if not doc_path.exists():
        return jsonify(error="Document not found"), 404
    try:
        from server.thumbnail import get_document_thumbnail as gen_thumb
    except ImportError:
        from thumbnail import get_document_thumbnail as gen_thumb
    result = gen_thumb(str(doc_path))
    if result.get("thumbnail"):
        return jsonify(thumbnail=result["thumbnail"])
    return jsonify(thumbnail=None)

# ═══════════════════════════════════════════════════════════════════════════════
# ZIP UPLOAD EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def identify_doc_type_from_filename(filename: str) -> tuple:
    """Identify document type from filename. Returns (doc_type, confidence)."""
    lower = filename.lower().replace("_", " ").replace("-", " ")
    patterns = {
        "pans": ["pans", "pre arrival", "prearrival", "pre-arrival"],
        "issc": ["issc", "ship security cert", "shipsecurity"],
        "csr": ["csr", "continuous synopsis", "synopsis record"],
        "dos": ["dos", "declaration of security", "decl sec", "decl_sec"],
        "crew_list": ["crew", "fal5", "fal 5", "fal_5", "crew_list"],
        "fal6": ["fal6", "fal 6", "fal_6", "passenger", "pax"],
        "fal7": ["fal7", "fal 7", "fal_7", "dangerous", "dg", "hazmat"],
        "armed_guards": ["armed", "guard", "weapon", "pcasp"],
        "isps_checklist": ["checklist", "isps_check", "check_list", "navy check"],
        "pi_certificate": ["p&i", "p_i", "pi_cert", "protection indem", "club cert", "coe"],
        "hull_machinery": ["hull", "h&m", "h_m", "machinery"],
        "ship_particulars": ["particular", "vessel detail", "ship_part", "ship particulars"],
    }
    for doc_type, pats in patterns.items():
        for p in pats:
            if p in lower:
                return doc_type, 0.9
    return "other", 0.1

@app.route("/api/vessels/<int:call_id>/documents/zip", methods=["POST"])
@jwt_required()
def upload_zip_documents(call_id):
    """
    Accepts JSON: { zip_b64: "...", zip_filename: "archive.zip" }
    Extracts ZIP, identifies document types, and processes each file.
    """
    uid = int(get_jwt_identity())
    data = request.json or {}
    zip_b64 = data.get("zip_b64", "")
    zip_filename = data.get("zip_filename", "archive.zip")
    
    if not zip_b64:
        return jsonify(error="No ZIP data provided"), 400
    
    db = get_db()
    vessel = row_to_dict(db.execute("SELECT * FROM vessel_calls WHERE id=?", (call_id,)).fetchone())
    if not vessel:
        db.close()
        return jsonify(error="Vessel call not found"), 404
    
    doc_rec = row_to_dict(db.execute("SELECT * FROM vessel_documents WHERE call_id=?", (call_id,)).fetchone())
    if not doc_rec:
        db.execute("INSERT INTO vessel_documents(call_id,submitted_by) VALUES(?,?)", (call_id, uid))
        db.commit()
    
    results = {}
    extracted_files = []
    
    try:
        zip_bytes = base64.b64decode(zip_b64)
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / zip_filename
            with open(zip_path, "wb") as f:
                f.write(zip_bytes)
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for zinfo in zf.namelist():
                    if zinfo.endswith('/'):
                        continue
                    ext = Path(zinfo).suffix.lower()
                    if ext not in ['.pdf', '.docx', '.doc', '.eml', '.png', '.jpg', '.jpeg', '.tif', '.tiff']:
                        continue
                    
                    file_bytes = zf.read(zinfo)
                    file_b64 = base64.b64encode(file_bytes).decode()
                    extracted_files.append({
                        "filename": Path(zinfo).name,
                        "b64": file_b64,
                        "doc_type": "other"
                    })
    
        for ef in extracted_files:
            doc_type, confidence = identify_doc_type_from_filename(ef["filename"])
            ef["doc_type"] = doc_type
            ef["confidence"] = confidence
            
            ext = Path(ef["filename"]).suffix
            save_name = f"{call_id}_{doc_type}_{uuid.uuid4().hex[:8]}{ext}"
            save_path = UPLOAD_DIR / save_name
            with open(save_path, "wb") as f:
                f.write(base64.b64decode(ef["b64"]))
            
            ocr_result = run_ocr(ef["b64"], ef["filename"])
            text = ocr_result.get("text", "")
            method = ocr_result.get("method", "unknown")
            
            db.execute(f"""
                UPDATE vessel_documents
                SET doc_{doc_type}_path=?,
                    doc_{doc_type}_text=?,
                    doc_{doc_type}_received=1,
                    updated_at=datetime('now')
                WHERE call_id=?
            """, (str(save_path), text, call_id))
            
            results[ef["filename"]] = {"doc_type": doc_type, "method": method, "chars": len(text), "saved": save_name, "confidence": confidence}
        
        db.execute("UPDATE vessel_calls SET status='documents_submitted',updated_at=datetime('now') WHERE id=?", (call_id,))
        log_action(db, call_id, uid, "documents_uploaded_zip", json.dumps(list(results.keys())))
        db.commit()
        return jsonify(ok=True, ocr_results=results, extracted_files=extracted_files)
    except Exception as e:
        db.close()
        return jsonify(error=f"ZIP extraction failed: {str(e)}"), 500

# ═══════════════════════════════════════════════════════════════════════════════
# STATIC FILES (serve the frontend)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    client_dir = BASE_DIR / ".." / "client"
    if path and (client_dir / path).exists():
        return send_from_directory(str(client_dir), path)
    return send_from_directory(str(client_dir), "index.html")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

# Always ensure DB is initialised (covers gunicorn cold-start on Render)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ensure_db()
load_config()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"[OK] ISPS HBT System running on http://localhost:{port}")
    print(f"  DB: {DB_PATH}")
    print(f"  Uploads: {UPLOAD_DIR}")
    app.run(host="0.0.0.0", port=port, debug=False)
