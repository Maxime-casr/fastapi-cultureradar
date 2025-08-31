# app/routes/login.py
import secrets, hashlib, os
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Utilisateur,EmailVerificationToken
from app.schemas import LoginRequest
from app.auth import get_db, verify_password, create_access_token, get_current_user

from datetime import datetime, timedelta, timezone
from app.utils.email import send_email

router = APIRouter(tags=["Login"])
verify_router = APIRouter(prefix="/auth", tags=["Auth"])

APP_PUBLIC_URL = os.getenv("APP_PUBLIC_URL", "http://localhost:4200")
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000")

@router.post("/login")
def login(credentials: dict, db: Session = Depends(get_db)):
    # credentials: { "email": str, "mot_de_passe": str }
    user = db.query(Utilisateur).filter(Utilisateur.email == credentials["email"]).first()
    if not user or not verify_password(credentials["mot_de_passe"], user.mot_de_passe):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
    if not user.is_email_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email non vérifié")
    token = create_access_token(sub=str(user.id))
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user.id, "email": user.email, "nom": user.nom}}

@verify_router.get("/verify-email")
def verify_email(token: str = Query(...), db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    rec = (db.query(EmailVerificationToken)
             .filter(EmailVerificationToken.token_hash == token_hash).first())
    if not rec:
        raise HTTPException(400, "Lien invalide")
    if rec.expires_at < datetime.now(timezone.utc):
        db.delete(rec); db.commit()
        raise HTTPException(400, "Lien expiré")

    user = db.get(Utilisateur, rec.user_id)
    if not user:
        db.delete(rec); db.commit()
        raise HTTPException(400, "Utilisateur introuvable")

    user.is_email_verified = True
    db.delete(rec)
    db.commit()
    return {"ok": True}
