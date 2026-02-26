from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
import sqlite3
import smtplib
import secrets
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = FastAPI(title="SynthFrame API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

# ── CONFIG (set via environment variables) ──
SMTP_EMAIL    = os.getenv("SMTP_EMAIL", "")          # your Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")       # Gmail app password
NOTIFY_EMAIL  = os.getenv("NOTIFY_EMAIL", "")        # where to send notifications
ADMIN_USER    = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS    = os.getenv("ADMIN_PASS", "synthframe123")
DB_PATH       = os.getenv("DB_PATH", "leads.db")

# ── DATABASE ──
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            company     TEXT,
            industry    TEXT,
            description TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ── SCHEMAS ──
class LeadIn(BaseModel):
    name: str
    email: EmailStr
    company: Optional[str] = ""
    industry: Optional[str] = ""
    description: Optional[str] = ""

class LeadOut(BaseModel):
    id: int
    name: str
    email: str
    company: str
    industry: str
    description: str
    created_at: str

# ── AUTH ──
def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USER)
    ok_pass = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ── EMAIL ──
def send_notification(lead: LeadIn):
    if not SMTP_EMAIL or not SMTP_PASSWORD or not NOTIFY_EMAIL:
        print("⚠️  Email not configured — skipping notification")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎯 New SynthFrame Lead: {lead.name}"
        msg["From"] = SMTP_EMAIL
        msg["To"] = NOTIFY_EMAIL

        html = f"""
        <html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
          <h2 style="color:#0a0a0a;border-bottom:2px solid #c8f04a;padding-bottom:12px">
            New Lead — SynthFrame
          </h2>
          <table style="width:100%;border-collapse:collapse;margin-top:16px">
            <tr><td style="padding:10px 0;color:#5c5a55;width:120px">Name</td>
                <td style="padding:10px 0;font-weight:600">{lead.name}</td></tr>
            <tr style="background:#f8f7f4"><td style="padding:10px 0;color:#5c5a55">Email</td>
                <td style="padding:10px 0"><a href="mailto:{lead.email}">{lead.email}</a></td></tr>
            <tr><td style="padding:10px 0;color:#5c5a55">Company</td>
                <td style="padding:10px 0">{lead.company or "—"}</td></tr>
            <tr style="background:#f8f7f4"><td style="padding:10px 0;color:#5c5a55">Industry</td>
                <td style="padding:10px 0">{lead.industry or "—"}</td></tr>
          </table>
          <div style="margin-top:24px;padding:16px;background:#f2f1ee;border-radius:12px">
            <p style="color:#5c5a55;margin:0 0 8px;font-size:13px">PROJECT DESCRIPTION</p>
            <p style="margin:0;line-height:1.6">{lead.description or "No description provided."}</p>
          </div>
          <p style="margin-top:24px;font-size:12px;color:#a09e97">
            Received {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}
          </p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, NOTIFY_EMAIL, msg.as_string())
        print(f"✅ Email sent for lead: {lead.email}")
    except Exception as e:
        print(f"❌ Email failed: {e}")

# ── ROUTES ──
@app.get("/")
def root():
    return {"status": "SynthFrame API is running 🚀"}

@app.post("/leads", status_code=201)
def create_lead(lead: LeadIn, db: sqlite3.Connection = Depends(get_db)):
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO leads (name, email, company, industry, description, created_at) VALUES (?,?,?,?,?,?)",
        (lead.name, lead.email, lead.company, lead.industry, lead.description, now)
    )
    db.commit()
    send_notification(lead)
    return {"message": "Lead received. We'll be in touch soon!"}

@app.get("/admin/leads")
def list_leads(db: sqlite3.Connection = Depends(get_db), _=Depends(verify_admin)):
    rows = db.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.delete("/admin/leads/{lead_id}")
def delete_lead(lead_id: int, db: sqlite3.Connection = Depends(get_db), _=Depends(verify_admin)):
    db.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    db.commit()
    return {"message": "Deleted"}
