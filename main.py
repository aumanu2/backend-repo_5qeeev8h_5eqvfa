import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import create_document, get_documents, db
from schemas import Profile, Post, Room, AuthCode, Message

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
    # Convert datetimes to isoformat strings for JSON
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
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


# ---------------------------
# Passwordless Auth (Magic Code)
# ---------------------------
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")

class RequestCodeBody(BaseModel):
    email: EmailStr

class VerifyCodeBody(BaseModel):
    email: EmailStr
    code: str

class VerifyResponse(BaseModel):
    token: str
    email: EmailStr
    profile: Optional[dict] = None

SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "1440"))  # default 1 day
CODE_TTL_MINUTES = int(os.getenv("CODE_TTL_MINUTES", "10"))


def _now():
    return datetime.now(timezone.utc)


@app.post("/api/auth/request-code")
def request_code(payload: RequestCodeBody):
    try:
        # generate 6-digit code
        code = f"{secrets.randbelow(1000000):06d}"
        expires_at = _now() + timedelta(minutes=CODE_TTL_MINUTES)
        auth_code = AuthCode(email=payload.email, code=code, expires_at=expires_at, used=False)
        create_document("authcode", auth_code)
        # In real app, send email via provider. In demo, optionally return code.
        resp = {"status": "ok", "message": "Code sent"}
        if DEMO_MODE:
            resp["debug_code"] = code
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/verify", response_model=VerifyResponse)
def verify_code(payload: VerifyCodeBody):
    try:
        # find latest unexpired, unused code
        codes = get_documents("authcode", {"email": payload.email}, limit=50)
        codes_sorted = sorted(codes, key=lambda d: d.get("created_at", 0), reverse=True)
        valid = None
        for c in codes_sorted:
            if c.get("used"):
                continue
            exp = c.get("expires_at")
            if isinstance(exp, str):
                try:
                    exp = datetime.fromisoformat(exp)
                except Exception:
                    exp = _now() - timedelta(seconds=1)
            if exp and exp < _now():
                continue
            if c.get("code") == payload.code:
                valid = c
                break
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        # mark code as used (best-effort)
        try:
            if db:
                db["authcode"].update_one({"_id": valid["_id"]}, {"$set": {"used": True, "updated_at": _now()}})
        except Exception:
            pass
        # create session token
        token = secrets.token_urlsafe(32)
        session = {
            "email": str(payload.email),
            "token": token,
            "created_at": _now(),
            "expires_at": _now() + timedelta(minutes=SESSION_TTL_MINUTES),
        }
        if db:
            db["session"].insert_one(session)
        # attach profile if exists
        profs = get_documents("profile", {"email": str(payload.email)}, limit=1)
        profile = to_public(profs[0]) if profs else None
        return VerifyResponse(token=token, email=payload.email, profile=profile)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _require_session(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    # validate token from db
    if db is None:
        return token  # fallback in dev if db missing
    sess = db["session"].find_one({"token": token})
    if not sess:
        raise HTTPException(status_code=401, detail="Invalid session")
    exp = sess.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            exp = _now() - timedelta(seconds=1)
    if exp and exp < _now():
        raise HTTPException(status_code=401, detail="Session expired")
    return str(sess.get("email"))


@app.get("/api/me")
def me(authorization: Optional[str] = Header(default=None)):
    try:
        email = _require_session(authorization)
        profs = get_documents("profile", {"email": email}, limit=1)
        return {"email": email, "profile": to_public(profs[0]) if profs else None}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------
# Messages and Realtime (WebSocket)
# ---------------------------

@app.post("/api/rooms/{room_id}/messages", response_model=InsertResponse)
def post_message(room_id: str, message: Message, authorization: Optional[str] = Header(default=None)):
    try:
        sender_email = _require_session(authorization)
        data = message.model_dump()
        data["room_id"] = room_id
        data["sender_email"] = data.get("sender_email") or sender_email
        inserted_id = create_document("message", data)
        # broadcast over websocket if connections exist
        payload = to_public({"id": inserted_id, **data, "created_at": datetime.now(timezone.utc)})
        try:
            manager.broadcast(room_id, payload)
        except Exception:
            pass
        return {"id": inserted_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rooms/{room_id}/messages")
def list_messages(room_id: str, limit: int = Query(50, le=200)):
    try:
        docs = get_documents("message", {"room_id": room_id}, limit=limit)
        docs_sorted = sorted(docs, key=lambda d: d.get("created_at", 0), reverse=True)
        return [to_public(d) for d in docs_sorted]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active.setdefault(room_id, []).append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        conns = self.active.get(room_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self.active.pop(room_id, None)

    async def send_personal(self, websocket: WebSocket, data):
        await websocket.send_json(data)

    async def broadcast(self, room_id: str, data):
        conns = self.active.get(room_id, [])
        for ws in list(conns):
            try:
                await ws.send_json(data)
            except Exception:
                try:
                    ws.close()
                except Exception:
                    pass
                self.disconnect(room_id, ws)


manager = ConnectionManager()


@app.websocket("/ws/rooms/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, token: Optional[str] = Query(default=None)):
    # Simple token validation
    try:
        if token:
            # validate token (best-effort)
            if db is not None:
                sess = db["session"].find_one({"token": token})
                if not sess:
                    await websocket.close(code=4001)
                    return
        await manager.connect(room_id, websocket)
        while True:
            data = await websocket.receive_json()
            # Expect { content: str, sender_id?: str }
            msg = {
                "room_id": room_id,
                "content": data.get("content"),
                "sender_id": data.get("sender_id"),
                "created_at": datetime.now(timezone.utc),
            }
            # store
            try:
                if db is not None:
                    db["message"].insert_one({**msg, "updated_at": datetime.now(timezone.utc)})
            except Exception:
                pass
            await manager.broadcast(room_id, to_public(msg))
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception:
        # On any error, close connection
        try:
            await websocket.close()
        except Exception:
            pass
        manager.disconnect(room_id, websocket)


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
