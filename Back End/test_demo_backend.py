import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import app

client = TestClient(app)

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    print("[OK] Health check passed")

def test_sample_data():
    res = client.get("/sample-data")
    assert res.status_code == 200
    data = res.json()
    assert "emails" in data
    assert len(data["emails"]) >= 30
    assert data["profile"]["degree"] == "BSCS"
    print(f"[OK] Synthetic sample data loaded ({len(data['emails'])} emails)")

def test_process_logic():
    res = client.get("/sample-data")
    sample = res.json()
    payload = {
        "profile": sample["profile"],
        "emails": sample["emails"][:5]
    }
    res = client.post("/process", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "ranked_opportunities" in data
    assert "discarded" in data
    print(f"[OK] AI Process pipeline executed: {len(data['ranked_opportunities'])} ranked, {len(data['discarded'])} discarded")

def test_in_memory_bookmarks_and_checklists():
    user_id = "test-recruiter-123"
    # Save profile
    prof_payload = {
        "user_id": user_id,
        "profile": {
            "degree": "BSCS", "semester": 6, "cgpa": 3.6,
            "skills": ["Python", "React"], "preferred_opportunity_types": ["internship"],
            "location_preference": "Lahore", "financial_need": False, "total_semesters": 8
        }
    }
    res = client.post("/profile", json=prof_payload)
    assert res.status_code == 200
    
    # Save bookmark
    bm_payload = {
        "user_id": user_id,
        "opportunity_id": "1",
        "opportunity_data": {"id": 1, "title": "Cloud Security Intern", "org": "CloudSec"}
    }
    res = client.post("/bookmarks", json=bm_payload)
    assert res.status_code == 200
    
    # Fetch bookmarks
    res = client.get(f"/bookmarks/{user_id}")
    assert res.status_code == 200
    assert res.json()["count"] == 1
    print("[OK] In-memory profile & bookmark storage verified (No MySQL needed)")

def test_demo_reset():
    user_id = "test-recruiter-123"
    res = client.post("/demo/reset", data={"user_id": user_id})
    assert res.status_code == 200
    assert res.json()["status"] == "reset"
    
    # Bookmarks should be cleared after reset
    res = client.get(f"/bookmarks/{user_id}")
    assert res.status_code == 200
    assert res.json()["count"] == 0
    print("[OK] Demo Session Reset endpoint verified")

if __name__ == "__main__":
    test_health()
    test_sample_data()
    test_process_logic()
    test_in_memory_bookmarks_and_checklists()
    test_demo_reset()
    print("\nALL BACKEND VERIFICATION TESTS PASSED SUCCESSFULLY!")
