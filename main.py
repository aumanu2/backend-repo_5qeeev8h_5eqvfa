import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import create_document, get_documents, db
from schemas import Profile, Post, Room

app = FastAPI(title="Youth Founder Network API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class InsertResponse(BaseModel):
    id: str


def to_public(doc: dict) -> dict:
    if not doc:
        return doc
    d = doc.copy()
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


@app.get("/")
def read_root():
    return {"message": "Youth Founder Network API is running"}


# Profiles
INVITE_CODE = os.getenv("INVITE_CODE")

@app.post("/api/profiles", response_model=InsertResponse)
def create_profile(profile: Profile, x_invite_code: Optional[str] = Header(default=None)):
    try:
        # Invite-only gating if INVITE_CODE is set in env
        if INVITE_CODE:
            if not x_invite_code or x_invite_code != INVITE_CODE:
                raise HTTPException(status_code=401, detail="Invalid or missing invite code")
        inserted_id = create_document("profile", profile)
        return {"id": inserted_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profiles")
def list_profiles():
    try:
        docs = get_documents("profile", {}, limit=100)
        return [to_public(d) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Posts
@app.post("/api/posts", response_model=InsertResponse)
def create_post(post: Post):
    try:
        inserted_id = create_document("post", post)
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/posts")
def list_posts():
    try:
        docs = get_documents("post", {}, limit=100)
        docs_sorted = sorted(docs, key=lambda d: d.get("created_at", 0), reverse=True)
        return [to_public(d) for d in docs_sorted]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Rooms
@app.post("/api/rooms", response_model=InsertResponse)
def create_room(room: Room):
    try:
        inserted_id = create_document("room", room)
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rooms")
def list_rooms():
    try:
        docs = get_documents("room", {}, limit=50)
        docs_sorted = sorted(docs, key=lambda d: d.get("created_at", 0), reverse=True)
        return [to_public(d) for d in docs_sorted]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
