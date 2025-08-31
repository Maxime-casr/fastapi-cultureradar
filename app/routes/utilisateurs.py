# app/routes/utilisateurs.py
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.auth import get_current_user, hash_password
from app.utils.email import send_email
from app.utils.verification import make_verif_token, verification_email_html
from app.database import SessionLocal
from app import models, schemas

APP_PUBLIC_URL = os.getenv("APP_PUBLIC_URL", "http://localhost:4200")

router = APIRouter(prefix="/utilisateurs", tags=["Utilisateurs"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.UtilisateurOut)
def create_user(body: schemas.UtilisateurCreate,
                background: BackgroundTasks,     # ⬅️ ajouté
                db: Session = Depends(get_db)):
    if db.query(models.Utilisateur).filter(models.Utilisateur.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email déjà utilisé")

    user = models.Utilisateur(
        nom=body.nom,
        email=body.email,
        mot_de_passe=hash_password(body.mot_de_passe),
        age=body.age,
        preferred_slot=body.preferred_slot,
        available_days=body.available_days,
        mobility=body.mobility,
    )
    try:
        db.add(user); db.commit(); db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email déjà utilisé")

    # ⬇️ envoyer l’e-mail de vérification ici
    token = make_verif_token(db, user)
    link = f"{APP_PUBLIC_URL}/verify-email?token={token}"
    html = verification_email_html(link, user.nom or user.email)
    background.add_task(send_email, user.email, "Vérifie ton e-mail", html)

    return user

@router.get("/me", response_model=schemas.UtilisateurOut)
def get_me(current_user: models.Utilisateur = Depends(get_current_user)):
    return current_user

@router.get("/me/subscription")
def get_subscription_status(current_user: models.Utilisateur = Depends(get_current_user)):
    return {
        "is_abonne": bool(getattr(current_user, "is_abonne", False)),
        "premium_since": getattr(current_user, "premium_since", None),
    }

@router.post("/me/subscribe")
def subscribe(current_user: models.Utilisateur = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if getattr(current_user, "is_abonne", False):
        return {"ok": True, "is_abonne": True, "premium_since": current_user.premium_since}
    current_user.is_abonne = True
    current_user.premium_since = datetime.now(timezone.utc)
    db.add(current_user); db.commit(); db.refresh(current_user)
    return {"ok": True, "is_abonne": True, "premium_since": current_user.premium_since}

@router.post("/me/unsubscribe")
def unsubscribe(current_user: models.Utilisateur = Depends(get_current_user),
                db: Session = Depends(get_db)):
    if not getattr(current_user, "is_abonne", False):
        return {"ok": True, "is_abonne": False, "premium_since": None}
    current_user.is_abonne = False
    current_user.premium_since = None
    db.add(current_user); db.commit(); db.refresh(current_user)
    return {"ok": True, "is_abonne": False, "premium_since": None}

@router.post("/utilisateurs/{id}/promote", response_model=schemas.UtilisateurOut)
def promote_user(id: int,
                 db: Session = Depends(get_db),
                 current_user: models.Utilisateur = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé à l’admin")
    user = db.query(models.Utilisateur).get(id)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    user.role = "organizer"
    db.add(user); db.commit(); db.refresh(user)
    return user



