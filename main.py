from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import JSONResponse
import smtplib
import secrets
import os
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

app = FastAPI(title="SynthFrame API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.options("/{rest_of_path:path}")
async def preflight(rest_of_path: str):
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })

security = HTTPBasic()

# ── CONFIG ──
SMTP_EMAIL     = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
NOTIFY_EMAIL   = os.getenv("NOTIFY_EMAIL", "")
ADMIN_USER     = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS     = os.getenv("ADMIN_PASS", "synthframe123")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "https://ofcgfpidbkttdkeosyeg.supabase.co")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9mY2dmcGlkYmt0dGRrZW9zeWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM1MDkzNDcsImV4cCI6MjA4OTA4NTM0N30.DEeNHTL4VRsIU9ZENy8ADvAyWBFvFxG8vD5kAGASqI8")

SUPA_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

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
def send_notification(lead: dict):
    if not SMTP_EMAIL or not SMTP_PASSWORD or not NOTIFY_EMAIL:
        print("Email not configured — skipping")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"New SynthFrame Lead: {lead['name']}"
        msg["From"] = SMTP_EMAIL
        msg["To"] = NOTIFY_EMAIL
        html = f"""
        <html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
          <h2 style="color:#0a0a0a;border-bottom:2px solid #c8f04a;padding-bottom:12px">New Lead - SynthFrame</h2>
          <table style="width:100%;border-collapse:collapse;margin-top:16px">
            <tr><td style="padding:10px 0;color:#5c5a55;width:120px">Name</td>
                <td style="padding:10px 0;font-weight:600">{lead['name']}</td></tr>
            <tr><td style="padding:10px 0;color:#5c5a55">Email</td>
                <td style="padding:10px 0">{lead['email']}</td></tr>
            <tr><td style="padding:10px 0;color:#5c5a55">Company</td>
                <td style="padding:10px 0">{lead.get('company') or '-'}</td></tr>
            <tr><td style="padding:10px 0;color:#5c5a55">Industry</td>
                <td style="padding:10px 0">{lead.get('industry') or '-'}</td></tr>
          </table>
          <div style="margin-top:24px;padding:16px;background:#f2f1ee;border-radius:12px">
            <p style="color:#5c5a55;margin:0 0 8px;font-size:13px">DESCRIPTION</p>
            <p style="margin:0;line-height:1.6">{lead.get('description') or 'No description.'}</p>
          </div>
          <p style="margin-top:24px;font-size:12px;color:#a09e97">Received {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>
        </body></html>
        """
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SMTP_EMAIL, SMTP_PASSWORD)
            s.sendmail(SMTP_EMAIL, NOTIFY_EMAIL, msg.as_string())
        print(f"Email sent: {lead['email']}")
    except Exception as e:
        print(f"Email failed: {e}")

# ── ROUTES ──
@app.get("/")
def root():
    return {"status": "SynthFrame API is running"}

@app.post("/leads", status_code=201)
async def create_lead(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name        = str(body.get("name") or "").strip()
    email       = str(body.get("email") or "").strip()
    company     = str(body.get("company") or "").strip()
    industry    = str(body.get("industry") or "").strip()
    description = str(body.get("description") or "").strip()

    if not name or not email or "@" not in email:
        raise HTTPException(status_code=422, detail="name and valid email are required")

    # Save to Supabase
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{SUPABASE_URL}/rest/v1/leads",
            headers=SUPA_HEADERS,
            json={"name": name, "email": email, "company": company,
                  "industry": industry, "description": description}
        )
        if res.status_code not in (200, 201):
            print(f"Supabase error: {res.text}")
            raise HTTPException(status_code=500, detail="Failed to save lead")

    send_notification({"name": name, "email": email, "company": company,
                       "industry": industry, "description": description})

    return {"message": "Lead received. We'll be in touch soon!"}

@app.get("/admin/leads")
async def list_leads(_=Depends(verify_admin)):
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/leads?order=created_at.desc",
            headers=SUPA_HEADERS
        )
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch leads")
        return res.json()

@app.delete("/admin/leads/{lead_id}")
async def delete_lead(lead_id: int, _=Depends(verify_admin)):
    async with httpx.AsyncClient() as client:
        res = await client.delete(
            f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}",
            headers=SUPA_HEADERS
        )
        if res.status_code not in (200, 204):
            raise HTTPException(status_code=500, detail="Failed to delete lead")
    return {"message": "Deleted"}
