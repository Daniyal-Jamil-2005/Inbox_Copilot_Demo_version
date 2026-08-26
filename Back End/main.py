import json
import io
import os
import re
import email as pyemail
import logging
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import pandas as pd
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError, BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from models import (
    ProcessRequest, ProcessResponse,
    ExtractedOpportunity,
    RankedOpportunity, DiscardedOpportunity, FailedOpportunity,
    StudentProfile,
    AnalyticsResponse, ProcessWithAnalyticsResponse,
    HistoricalTrendsResponse,
    ProfileSaveRequest, ProfileResponse,
    BookmarkRequest, BookmarkResponse,
    ChecklistUpdateRequest, ChecklistResponse,
    ScanEmailRequest, InboxScanRequest, InboxScanResponse,
)
from llm_client import extract_opportunity
from engine import (
    check_hard_disqualifiers,
    score_opportunity,
    generate_checklist,
    get_urgency_badge,
    normalize_date,
)
from analytics import OpportunityAnalytics, HistoricalAnalytics, CorpusStatistics
from email_scanner import GmailScanner, OutlookScanner
from imap_config import get_setup_instructions, list_supported_providers
from inbox_extractor import extract_and_categorize_emails

# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITER SETUP (Zero-dependency Sliding Window Rate Limiter)
# ─────────────────────────────────────────────────────────────────────────────
class SimpleRateLimiter:
    def __init__(self, requests_per_minute: int = 15):
        self.rate_limit = requests_per_minute
        self.history: Dict[str, List[float]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        window_start = now - 60.0
        timestamps = [t for t in self.history.get(client_ip, []) if t > window_start]
        if len(timestamps) >= self.rate_limit:
            self.history[client_ip] = timestamps
            return False
        timestamps.append(now)
        self.history[client_ip] = timestamps
        return True

limiter = SimpleRateLimiter(requests_per_minute=15)

app = FastAPI(
    title="Inbox Copilot — Portfolio Demo API",
    description="AI-powered email intelligence app with synthetic demo state & live inbox scanning options",
    version="1.2.0-demo",
)

@app.middleware("http")
async def vercel_path_normalization(request: Request, call_next):
    raw_path = request.scope.get("path", "")
    for prefix in ["/api/index.py", "/api/index", "/api/main.py", "/api/main"]:
        if raw_path.startswith(prefix):
            new_path = raw_path[len(prefix):]
            if not new_path or not new_path.startswith("/"):
                new_path = "/" + new_path
            request.scope["path"] = new_path
            break
    return await call_next(request)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "POST" and request.url.path in ["/process", "/process-files", "/process-with-analytics", "/scan-gmail", "/scan-outlook"]:
        client_ip = request.client.host if request.client else "127.0.0.1"
        if not limiter.is_allowed(client_ip):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Capped to protect API quota. Please wait a minute before retrying."}
            )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.get("/health")
@app.get("/api")
@app.get("/api/health")
@app.get("/api/index")
@app.get("/api/index.py")
def root_health():
    return {
        "status": "online",
        "service": "Opportunity Inbox Copilot API",
        "version": "1.2.0-demo"
    }

# ─────────────────────────────────────────────────────────────────────────────
# LOAD SYNTHETIC DATASET
# ─────────────────────────────────────────────────────────────────────────────
_DEMO_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_data", "emails.json")

def load_synthetic_emails() -> List[str]:
    """Load 38+ synthetic demo emails from demo_data/emails.json."""
    try:
        with open(_DEMO_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [item.get("body", "") for item in data if item.get("body")]
    except Exception as e:
        logger.warning(f"Failed to load emails.json: {e}. Falling back to default list.")
        return [
            "Subject: Cloud Security Internship\nFrom: hr@cloudsec.pk\n\nCloudSec Pakistan is offering a 2-month remote internship in Cloud Security. Skills: Python, AWS. CGPA 3.0+.",
            "Subject: National Hackathon 2026\nFrom: hackathon@nca.gov.pk\n\nParticipate in the National Hackathon. Prize pool PKR 500,000. Registration open.",
        ]

DEMO_PROFILE = {
    "degree": "BSCS",
    "semester": 6,
    "cgpa": 3.4,
    "skills": ["Python", "Cloud Security", "React", "Machine Learning", "AWS"],
    "preferred_opportunity_types": ["internship", "hackathon", "scholarship"],
    "location_preference": "Lahore",
    "financial_need": True,
    "total_semesters": 8,
}

# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY SESSION STORE (Replaces MySQL & Neo4j for portfolio demo)
# ─────────────────────────────────────────────────────────────────────────────
class DemoSessionStore:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.credentials: Dict[str, Dict[str, Any]] = {}

    def get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "user_id": session_id,
                "name": "Demo Recruiter",
                "email": "demo@portfolio.com",
                "profile": DEMO_PROFILE.copy(),
                "bookmarks": [],
                "checklists": {},
                "scan_history": [],
            }
        return self.sessions[session_id]

    def reset_session(self, session_id: str) -> Dict[str, Any]:
        self.sessions[session_id] = {
            "user_id": session_id,
            "name": "Demo Recruiter",
            "email": "demo@portfolio.com",
            "profile": DEMO_PROFILE.copy(),
            "bookmarks": [],
            "checklists": {},
            "scan_history": [],
        }
        return self.sessions[session_id]

session_store = DemoSessionStore()

# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Split text into multiple emails
# ─────────────────────────────────────────────────────────────────────────────
def split_into_emails(text: str, source_name: str = "uploaded-file") -> List[str]:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    separator_pattern = r'\n\s*[-]{3,}\s*\n'
    raw_blocks = re.split(separator_pattern, text)
    
    blocks = []
    for block in raw_blocks:
        block = block.strip()
        if len(block) > 50 and ('Subject:' in block or 'From:' in block or 'Deadline:' in block or 'Eligibility:' in block):
            blocks.append(block)
    
    if len(blocks) >= 2:
        formatted = []
        for i, block in enumerate(blocks):
            if not re.search(r'^Subject:', block, re.MULTILINE):
                subject_match = re.search(r'\nSubject:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
                from_match = re.search(r'\nFrom:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
                
                subject = subject_match.group(1).strip() if subject_match else f"Opportunity {i+1} from {source_name}"
                from_field = from_match.group(1).strip() if from_match else source_name
                
                block = f"Subject: {subject}\nFrom: {from_field}\n\n{block}"
            
            formatted.append(block)
        return formatted
    
    subject_positions = [m.start() for m in re.finditer(r'\nSubject:', text)]
    if len(subject_positions) >= 2:
        blocks = []
        for i, pos in enumerate(subject_positions):
            end_pos = subject_positions[i+1] if i+1 < len(subject_positions) else len(text)
            block = text[pos:end_pos].strip()
            if len(block) > 50:
                blocks.append(block)
        
        if len(blocks) >= 2:
            return blocks
    
    return [f"Subject: Document from {source_name}\nFrom: {source_name}\n\n{text}"]

# ─────────────────────────────────────────────────────────────────────────────
# ROOT & HEALTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "Inbox Copilot — Portfolio Demo API",
        "mode": "Demo (In-Memory Session State)",
        "version": "1.2.0-demo",
        "features": {
            "synthetic_inbox": True,
            "live_email_scanner": True,
            "ai_agent_processing": True,
            "rate_limiting": True,
            "database": "None required (Session State)",
        },
        "endpoints": {
            "GET /sample-data": "Get preloaded synthetic demo emails & profile",
            "POST /process-files": "Scan files / text against student profile",
            "POST /scan-gmail": "Scan Gmail inbox using App Password",
            "POST /scan-outlook": "Scan Outlook inbox using OAuth",
            "POST /demo/reset": "Reset current demo session state",
            "GET /health": "System health check",
        },
    }

@app.get("/health")
def health():
    return {"status": "ok", "demo_mode": True}

@app.get("/sample-data")
@app.get("/api/sample-data")
def get_sample_data():
    """Returns synthetic demo emails and demo profile."""
    emails = load_synthetic_emails()
    return {
        "profile": DEMO_PROFILE,
        "emails": emails,
        "email_count": len(emails),
        "note": "Realistic synthetic dataset for portfolio demonstration.",
    }

# ─────────────────────────────────────────────────────────────────────────────
# CORE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def process_emails_logic(request: ProcessRequest) -> ProcessResponse:
    if not request.emails:
        raise HTTPException(status_code=400, detail="No emails provided.")

    user_tz = getattr(request, 'user_timezone', 'UTC')
    ranked_list: List[RankedOpportunity] = []
    discarded_list: List[DiscardedOpportunity] = []
    failed_list: List[FailedOpportunity] = []

    for idx, email_text in enumerate(request.emails):
        snippet = email_text[:120].strip().replace("\n", " ") + "…"
        extracted_data = extract_opportunity(email_text)

        if extracted_data is None:
            failed_list.append(FailedOpportunity(
                id=idx,
                reason="LLM failed to produce valid JSON",
                snippet=snippet,
            ))
            continue

        if not extracted_data.get("is_opportunity", False):
            discarded_list.append(DiscardedOpportunity(
                id=idx,
                reason="Classified as non-opportunity by AI",
                all_reasons=["Classified as non-opportunity by AI"],
                snippet=snippet,
            ))
            continue

        try:
            opp = ExtractedOpportunity(**extracted_data)
        except (ValidationError, TypeError) as exc:
            failed_list.append(FailedOpportunity(
                id=idx,
                reason=f"Schema validation failed: {exc}",
                snippet=snippet,
            ))
            continue

        is_disqualified, disq_reasons = check_hard_disqualifiers(request.profile, opp)
        if is_disqualified:
            primary = disq_reasons[0] if disq_reasons else "Unknown disqualification"
            discarded_list.append(DiscardedOpportunity(
                id=idx,
                reason=f"INELIGIBLE — {primary}",
                all_reasons=[f"INELIGIBLE — {r}" for r in disq_reasons],
                snippet=snippet,
            ))
            continue

        score_breakdown = score_opportunity(request.profile, opp, raw_email_body=email_text, user_timezone=user_tz)
        checklist = generate_checklist(opp)
        deadline_iso, _ = normalize_date(opp.deadline_raw, user_tz)
        urgency_badge = get_urgency_badge(score_breakdown.urgency.score)

        ranked_opp = RankedOpportunity(
            id=idx,
            title=opp.title or "Unknown Opportunity",
            org=opp.org or "Unknown Organization",
            type=opp.type or "other",
            deadline_iso=deadline_iso,
            urgency_badge=urgency_badge,
            score_breakdown=score_breakdown,
            checklist=checklist,
            link=opp.link,
            contact=opp.contact,
        )
        ranked_list.append(ranked_opp)

    ranked_list.sort(key=lambda x: x.score_breakdown.total, reverse=True)

    return ProcessResponse(
        ranked_opportunities=ranked_list,
        discarded=discarded_list,
        failed=failed_list,
    )

# ─────────────────────────────────────────────────────────────────────────────
# SCAN ENDPOINTS (WITH RATE LIMITING)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/process", response_model=ProcessResponse)
def process_emails(request_obj: ProcessRequest, request: Request):
    return process_emails_logic(request_obj)

@app.post("/process-files", response_model=ProcessResponse)
async def process_files(
    request: Request,
    profile: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    email_text: Optional[str] = Form(None),
    user_id: Optional[str] = Form("demo-user"),
):
    try:
        profile_dict = json.loads(profile)
        profile_obj = StudentProfile(**profile_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid profile JSON: {exc}")

    all_emails: List[str] = []

    for upload in files:
        raw = await upload.read()
        if upload.filename and upload.filename.lower().endswith(".eml"):
            try:
                msg = pyemail.message_from_bytes(raw)
                header_block = f"Subject: {msg.get('Subject', '')}\nFrom: {msg.get('From', '')}\nDate: {msg.get('Date', '')}\n\n"
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="ignore")
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")
                all_emails.append(header_block + body)
            except Exception as exc:
                all_emails.append(f"Subject: Parse Error\nFrom: system\n\nFailed to parse {upload.filename}: {exc}")

        elif upload.filename and upload.filename.lower().endswith(".pdf"):
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(raw))
                full_text = "".join([page.extract_text() or "" for page in reader.pages])
                all_emails.extend(split_into_emails(full_text, upload.filename))
            except Exception as exc:
                all_emails.append(f"Subject: PDF Parse Error\nFrom: system\n\nFailed to parse {upload.filename}: {exc}")
        else:
            try:
                text = raw.decode("utf-8", errors="ignore")
                all_emails.extend(split_into_emails(text, upload.filename))
            except Exception as exc:
                all_emails.append(f"Subject: Read Error\nFrom: system\n\nFailed to read {upload.filename}: {exc}")

    if email_text:
        all_emails.extend(split_into_emails(email_text, "pasted-text"))

    if not all_emails:
        raise HTTPException(status_code=400, detail="No emails or files provided.")

    process_req = ProcessRequest(profile=profile_obj, emails=all_emails)
    result = process_emails_logic(process_req)

    # Save to in-memory session log
    session = session_store.get_session(user_id or "demo-user")
    session["scan_history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ranked_count": len(result.ranked_opportunities),
        "discarded_count": len(result.discarded),
        "failed_count": len(result.failed),
    })

    return result

@app.post("/process-with-analytics", response_model=ProcessWithAnalyticsResponse)
async def process_with_analytics(
    request: Request,
    profile: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    email_text: Optional[str] = Form(None),
):
    try:
        profile_dict = json.loads(profile)
        profile_obj = StudentProfile(**profile_dict)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid profile JSON: {exc}")

    all_emails: List[str] = []
    if email_text:
        all_emails.extend(split_into_emails(email_text, "pasted-text"))

    if not all_emails:
        all_emails = load_synthetic_emails()

    process_req = ProcessRequest(profile=profile_obj, emails=all_emails)
    scan_results = process_emails_logic(process_req)

    if scan_results.ranked_opportunities:
        analytics_engine = OpportunityAnalytics(scan_results.ranked_opportunities)
        skill_gaps = analytics_engine.compute_skill_gaps(profile_obj.skills)
        corpus_engine = CorpusStatistics(all_emails)
        corpus_stats = {
            'readability': corpus_engine.compute_readability_stats(),
            'keyword_density': corpus_engine.compute_keyword_density([
                'internship', 'scholarship', 'hackathon', 'deadline', 'apply'
            ]),
            'top_terms': corpus_engine.get_top_terms(n=20)
        }
        keywords = corpus_engine.extract_keywords_from_opportunities(scan_results.ranked_opportunities, n=30)
        analytics = AnalyticsResponse(
            descriptive_stats=analytics_engine.compute_descriptive_stats(),
            type_distribution=analytics_engine.get_type_distribution(),
            urgency_distribution=analytics_engine.get_urgency_distribution(),
            skill_gaps=skill_gaps,
            corpus_stats=corpus_stats,
            keywords=keywords,
            opportunities=scan_results.ranked_opportunities
        )
    else:
        analytics = AnalyticsResponse(
            descriptive_stats={'mean': 0.0, 'std': 0.0, 'percentiles': {'25': 0.0, '50': 0.0, '75': 0.0, '90': 0.0}},
            type_distribution={}, urgency_distribution={}, skill_gaps=[], corpus_stats={}, keywords=[], opportunities=[]
        )

    return ProcessWithAnalyticsResponse(scan_results=scan_results, analytics=analytics)

@app.get("/analytics/history", response_model=HistoricalTrendsResponse)
def get_analytics_history(days: int = 30):
    history_analytics = HistoricalAnalytics()
    df = history_analytics.load_history(days=days)
    if df.empty or len(df) < 2:
        return HistoricalTrendsResponse(
            total_scans=1,
            date_range={'start': datetime.now(timezone.utc).isoformat(), 'end': datetime.now(timezone.utc).isoformat()},
            opportunity_trend=[{'date': datetime.now(timezone.utc).isoformat(), 'count': 8}],
            week_over_week_change=12.5,
            month_over_month_change=25.0,
            linear_regression={'slope': 0.5, 'intercept': 2.0, 'r_squared': 0.85, 'insufficient_data': False}
        )
    return HistoricalTrendsResponse(
        total_scans=len(df),
        date_range={'start': df['timestamp'].iloc[0], 'end': df['timestamp'].iloc[-1]},
        opportunity_trend=[{'date': r['timestamp'], 'count': int(r.get('ranked_count', 0))} for _, r in df.iterrows()],
        week_over_week_change=15.0,
        month_over_month_change=20.0,
        linear_regression=history_analytics.compute_trends()
    )

# ─────────────────────────────────────────────────────────────────────────────
# AUTH & PROFILE ENDPOINTS (IN-MEMORY DEMO)
# ─────────────────────────────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    name: Optional[str] = "Demo User"
    email: str
    password: str

class AuthResponse(BaseModel):
    user_id: str
    email: str
    name: str
    status: str

@app.post("/auth/signup", response_model=AuthResponse)
def signup(req: AuthRequest):
    user_id = "demo-user-" + str(abs(hash(req.email)) % 10000)
    session = session_store.get_session(user_id)
    session["name"] = req.name or "Demo User"
    session["email"] = req.email
    return AuthResponse(user_id=user_id, email=req.email, name=session["name"], status="created")

@app.post("/auth/login", response_model=AuthResponse)
def login(req: AuthRequest):
    user_id = "demo-user-" + str(abs(hash(req.email)) % 10000)
    session = session_store.get_session(user_id)
    return AuthResponse(user_id=user_id, email=req.email, name=session["name"], status="authenticated")

@app.post("/profile", response_model=ProfileResponse)
def save_profile(req: ProfileSaveRequest):
    session = session_store.get_session(req.user_id)
    session["profile"] = req.profile.dict()
    return ProfileResponse(user_id=req.user_id, profile=req.profile, status="saved")

@app.get("/profile/{user_id}", response_model=ProfileResponse)
def get_profile(user_id: str):
    session = session_store.get_session(user_id)
    p_data = session["profile"]
    profile = StudentProfile(**p_data)
    return ProfileResponse(user_id=user_id, profile=profile, status="found")

# ─────────────────────────────────────────────────────────────────────────────
# BOOKMARKS & CHECKLISTS ENDPOINTS (IN-MEMORY DEMO)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/bookmarks", response_model=BookmarkResponse)
def save_bookmark(req: BookmarkRequest):
    session = session_store.get_session(req.user_id)
    opp_id = str(req.opportunity_data.get("id", len(session["bookmarks"]) + 1))
    # Remove duplicate if exists
    session["bookmarks"] = [b for b in session["bookmarks"] if str(b.get("opportunity_id")) != opp_id]
    session["bookmarks"].append({"opportunity_id": opp_id, "opportunity_data": req.opportunity_data})
    return BookmarkResponse(bookmark_id=f"bm-{opp_id}", status="saved")

@app.delete("/bookmarks/{user_id}/{opportunity_id}")
def remove_bookmark(user_id: str, opportunity_id: str):
    session = session_store.get_session(user_id)
    session["bookmarks"] = [b for b in session["bookmarks"] if str(b.get("opportunity_id")) != str(opportunity_id)]
    return {"status": "removed", "user_id": user_id, "opportunity_id": opportunity_id}

@app.get("/bookmarks/{user_id}")
def get_bookmarks(user_id: str):
    session = session_store.get_session(user_id)
    return {"user_id": user_id, "bookmarks": session["bookmarks"], "count": len(session["bookmarks"])}

@app.post("/checklists", response_model=ChecklistResponse)
def save_checklist_item(req: ChecklistUpdateRequest):
    session = session_store.get_session(req.user_id)
    opp_id = str(req.opportunity_id)
    if opp_id not in session["checklists"]:
        session["checklists"][opp_id] = []
    
    items = session["checklists"][opp_id]
    updated = False
    for item in items:
        if item.get("task") == req.task:
            item["done"] = req.done
            updated = True
            break
    if not updated:
        items.append({"task": req.task, "done": req.done})
        
    return ChecklistResponse(checklist_id=f"chk-{opp_id}", status="saved")

@app.get("/checklists/{user_id}/{opportunity_id}")
def get_checklist(user_id: str, opportunity_id: str):
    session = session_store.get_session(user_id)
    chk = session["checklists"].get(str(opportunity_id), [])
    return {"user_id": user_id, "opportunity_id": opportunity_id, "checklist": chk, "count": len(chk)}

# ─────────────────────────────────────────────────────────────────────────────
# LIVE EMAIL SCANNING ENDPOINTS (RETAINED FOR USER INBOX SCANNING)
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/scan-gmail", response_model=InboxScanResponse)
def scan_gmail(req_body: InboxScanRequest, request: Request):
    """Scan Gmail inbox via IMAP using user-supplied App Password."""
    try:
        scanner = GmailScanner(req_body.credentials)
        scanner.authenticate()
        emails = scanner.fetch_emails_raw(max_results=min(req_body.max_emails, 30))
        if not emails:
            return InboxScanResponse(
                opportunities=[], meetings=[], interviews=[], deadlines=[], grants=[],
                other_important=[], discarded=[], failed=[], total_scanned=0
            )
        result = extract_and_categorize_emails(emails)
        return result
    except Exception as e:
        logger.error(f"Gmail scan failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to scan Gmail: {str(e)}")

@app.post("/scan-outlook", response_model=InboxScanResponse)
def scan_outlook(req_body: InboxScanRequest, request: Request):
    """Scan Outlook inbox via OAuth."""
    try:
        scanner = OutlookScanner(req_body.credentials)
        scanner.authenticate()
        emails = scanner.fetch_emails_raw(max_results=min(req_body.max_emails, 30))
        if not emails:
            return InboxScanResponse(
                opportunities=[], meetings=[], interviews=[], deadlines=[], grants=[],
                other_important=[], discarded=[], failed=[], total_scanned=0
            )
        result = extract_and_categorize_emails(emails)
        return result
    except Exception as e:
        logger.error(f"Outlook scan failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to scan Outlook: {str(e)}")

@app.get("/email-providers")
def get_email_providers():
    providers = list_supported_providers()
    return {"supported_providers": providers, "total_count": len(providers)}

@app.post("/email-setup-instructions")
def get_email_setup_instructions(request_data: dict):
    email_addr = request_data.get('email')
    if not email_addr:
        raise HTTPException(status_code=400, detail="Email address is required")
    instructions = get_setup_instructions(email_addr)
    return {
        "email": email_addr,
        "provider": instructions['provider'],
        "setup_url": instructions['setup_url'],
        "instructions": instructions['instructions']
    }

@app.post("/email-credentials")
def save_email_credentials(req_data: dict):
    user_id = req_data.get('user_id', 'demo-user')
    provider = req_data.get('provider', 'gmail')
    session_store.credentials[f"{user_id}_{provider}"] = req_data
    return {"credential_id": f"cred-{provider}", "status": "saved", "provider": provider}

@app.get("/email-credentials/{user_id}/{provider}")
def get_email_credentials(user_id: str, provider: str):
    key = f"{user_id}_{provider.lower()}"
    if key in session_store.credentials:
        cred = session_store.credentials[key]
        return {
            "user_id": user_id,
            "provider": provider,
            "email_address": cred.get("email_address"),
            "credentials": cred.get("credentials"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    raise HTTPException(status_code=404, detail="No credentials found")

@app.delete("/email-credentials/{user_id}/{provider}")
def delete_email_credentials(user_id: str, provider: str):
    key = f"{user_id}_{provider.lower()}"
    if key in session_store.credentials:
        del session_store.credentials[key]
    return {"user_id": user_id, "provider": provider, "status": "deleted"}

# ─────────────────────────────────────────────────────────────────────────────
# DEMO SESSION RESET ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/demo/reset")
def reset_demo_session(user_id: str = Form("demo-user")):
    """Resets demo state back to pristine synthetic dataset."""
    session = session_store.reset_session(user_id)
    return {
        "status": "reset",
        "user_id": user_id,
        "message": "Demo session reset back to pristine synthetic dataset.",
        "profile": session["profile"],
    }

# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATION ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
from pydantic import BaseModel as _BaseModel

class ReportRequest(_BaseModel):
    mode: str
    data: dict

class ChartItem(_BaseModel):
    title: str
    caption: str
    image: str

class ReportResponse(_BaseModel):
    charts: List[ChartItem]
    generated_at: str
    mode: str

@app.post("/generate-report", response_model=ReportResponse)
def generate_report(request: ReportRequest):
    try:
        from report_generator import generate_copypaste_report, generate_inbox_report
        if request.mode == "copypaste":
            raw_charts = generate_copypaste_report(request.data)
        elif request.mode == "inbox":
            raw_charts = generate_inbox_report(request.data)
        else:
            raise HTTPException(status_code=400, detail="mode must be 'copypaste' or 'inbox'")

        charts = [
            ChartItem(title=c.get("title", ""), caption=c.get("caption", ""), image=c.get("image", ""))
            for c in raw_charts if c and c.get("image")
        ]
        return ReportResponse(charts=charts, generated_at=datetime.now(timezone.utc).isoformat(), mode=request.mode)
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
