# Inbox Copilot — Portfolio Demo Edition

[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat&logo=react)](https://reactjs.org)
[![LLM Agent](https://img.shields.io/badge/AI_Agent-Cerebras_llama3.1--8b-FF6B6B)](https://cerebras.ai)
[![Demo Mode](https://img.shields.io/badge/Demo_Mode-Database--Free_State-4ADE80)](https://github.com/Daniyal-Jamil-2005/Inbox_Copilot_Demo)

An AI-powered email and inbox intelligence application designed for university students to automatically parse, classify, and deterministically rank opportunities (internships, scholarships, hackathons, grants, fellowships) against their student vector profile.

This repository is a **standalone, recruiter-friendly Portfolio Demonstration** version of the main [Inbox Copilot](https://github.com/Daniyal-Jamil-2005/Inbox_Copilot) project.

---

## 🚀 Key Highlights of the Portfolio Demo

- **Zero Database Setup**: Eliminates MySQL and Neo4j requirements at runtime. State (user profile, synthetic email processing, bookmarks, checklists) is maintained via lightweight in-memory session storage in FastAPI.
- **Instant Interactive Exploration**: Preloaded with a realistic synthetic inbox of **38 fictional emails** covering internships, scholarships, hackathons, rejection letters, meeting invitations, cafeteria notices, and spam.
- **Live Inbox Scanning Retained**: Includes IMAP (Gmail App Passwords) and Outlook OAuth scanning for users who want to connect their actual live inbox.
- **Real AI Agent Backend**: Runs full LLM extraction (`Cerebras llama3.1-8b`) and 6-dimensional deterministic scoring out of 105.
- **Rate-Limited API Security**: Integrated `slowapi` rate-limiting protects the backend and AI quota against abuse.
- **Strict Server-Side Secret Hiding**: All AI/LLM API credentials reside strictly in server-side environment variables and are never bundled or exposed to the client.

---

## 🏗️ Demo Architecture

```text
                             RECRUITER / USER
                                    │
                                    ▼
                      ┌───────────────────────────┐
                      │    React 19 Frontend      │
                      │                           │
                      │  • Synthetic Inbox View   │
                      │  • Live Inbox Scan UI     │
                      │  • Demo Mode Indicator    │
                      └─────────────┬─────────────┘
                                    │
                                 HTTPS API
                                    │
                                    ▼
                      ┌───────────────────────────┐
                      │   FastAPI Demo Backend    │
                      │                           │
                      │  • SlowAPI Rate Limiting  │
                      │  • Session Manager        │
                      │  • Deterministic Engine   │
                      └─────────────┬─────────────┘
                                    │
                 ┌──────────────────┴──────────────────┐
                 │                                     │
                 ▼                                     ▼
        Synthetic Email Dataset                  AI / Agent Engine
       38 Realistic Emails (JSON)              Server-Side Secret Key
                 │                              (Cerebras / LLM)
                 ▼
        In-Memory Session State
      (Bookmarks, Profile, Checklists)
```

---

## 🔒 Security & Privacy Guarantees

1. **Server-Side API Key Protection**: The AI provider secret (`CEREBRAS_API_KEY`) exists **only** in the backend environment. Frontend variables do NOT contain any secret keys.
2. **API Rate Limiting**: All scanning and LLM extraction routes are capped per IP (e.g. max 15 scan requests / min) to prevent server overload or API quota exhaustion.
3. **No Database Leaks**: Synthetic demo sessions isolate data in temporary memory. Restarting the backend server restores a clean, pristine demo state.

---

## ⚡ Quick Start / Local Development

### Prerequisites
- **Python**: 3.10+
- **Node.js**: v18+ & `npm`

---

### 1. Backend Setup (FastAPI)

```bash
cd "Back End"

# Create virtual environment (optional but recommended)
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install clean dependencies
pip install -r requirements.txt

# Create your .env file from template
cp .env.example .env

# Add your server-side Cerebras API Key in .env:
# CEREBRAS_API_KEY=your_key_here

# Start the FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The FastAPI backend will run on `http://localhost:8000`. You can inspect the interactive OpenAPI documentation at `http://localhost:8000/docs`.

---

### 2. Frontend Setup (React)

Open a new terminal window:

```bash
cd "Front End"

# Install dependencies
npm install

# Start the React development server
npm start
```

The application will automatically open in your browser at `http://localhost:3000`.

---

## ⚙️ Environment Variables

### Backend (`Back End/.env`)
| Variable | Description | Default |
| :--- | :--- | :--- |
| `CEREBRAS_API_KEY` | Server-side secret key for Cerebras LLM extraction | *Required* |
| `DEMO_MODE` | Enables database-free in-memory session mode | `true` |
| `PORT` | Port for Uvicorn server | `8000` |
| `FRONTEND_URL` | Deployed frontend origin for CORS | `http://localhost:3000` |
| `RATE_LIMIT_PER_MINUTE` | Capped API calls per IP minute | `15` |

### Frontend (`Front End/.env`)
| Variable | Description | Default |
| :--- | :--- | :--- |
| `REACT_APP_API_URL` | URL of deployed or local FastAPI backend | `http://localhost:8000` |

---

## 🎯 Features Demonstrated

1. **Synthetic Inbox One-Click Load**: Instantly load and rank 38 preloaded emails against student profiles.
2. **Live Email Scanner**: Connect Gmail (App Password) or Outlook (OAuth) to extract real opportunities.
3. **6-Dimensional Deterministic Scoring Engine**:
   - Skill Relevance (55 pts max)
   - Deadline Urgency (15 pts max)
   - Opportunity Type Match (15 pts max)
   - Location Fit (10 pts max)
   - Financial Bonus (5 pts max)
   - Field Completeness (5 pts max)
4. **Noise Elimination**: Discards newsletters, lost-and-found posts, cafeteria menus, and library fine notices, displaying exact rejection reasons.
5. **Action Checklist Generation**: Priority-sorted tasks generated per opportunity.
6. **Analytics & PDF Export**: Compute descriptive statistics, skill gap analysis, and export PDF summaries.
7. **Reset Demo Session**: Restores pristine synthetic dataset and profile state with one click.

---

## 📄 License

This portfolio demonstration is released under the **MIT License**.
Original Full Version: [Inbox Copilot](https://github.com/Daniyal-Jamil-2005/Inbox_Copilot)
