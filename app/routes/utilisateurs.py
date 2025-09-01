# app/routes/utilisateurs.py
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import os

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

@router.get("/me", response_model=schemas.UtilisateurOut)
def get_me(current_user: models.Utilisateur = Depends(get_current_user)):
    return current_user


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

@router.put("/me", response_model=schemas.UtilisateurOut)
def update_me(
    body: schemas.UtilisateurUpdate,
    db: Session = Depends(get_db),
    current_user: models.Utilisateur = Depends(get_current_user),
):
    # on ne met à jour que les champs fournis (exclude_unset)
    data = body.model_dump(exclude_unset=True)

    # petite normalisation/validation légère
    if "nom" in data and data["nom"] is not None:
        data["nom"] = (data["nom"] or "").strip()
        if not data["nom"]:
            raise HTTPException(status_code=422, detail="Le nom ne peut pas être vide.")

    if "age" in data and data["age"] is not None:
        try:
            data["age"] = int(data["age"])
            if data["age"] < 0 or data["age"] > 120:
                raise ValueError()
        except Exception:
            raise HTTPException(status_code=422, detail="Âge invalide.")

    # mise à jour sélective
    for k, v in data.items():
        setattr(current_user, k, v)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/{id}/promote", response_model=schemas.UtilisateurOut)
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

def _subscription_info(u: models.Utilisateur) -> tuple[bool, datetime|None]:
    """Actif si is_abonne=True ET premium_since < 30 j."""
    since = getattr(u, "premium_since", None)
    if not getattr(u, "is_abonne", False) or since is None:
        return False, None
    expires = since + timedelta(days=30)
    return (datetime.now(timezone.utc) < expires), expires

@router.get("/me/subscription")
def get_subscription_status(current_user: models.Utilisateur = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    active, expires_at = _subscription_info(current_user)
    # (optionnel) auto-expirer en base
    if current_user.is_abonne and not active:
        current_user.is_abonne = False
        db.add(current_user); db.commit(); db.refresh(current_user)
    return {
        "is_active": active,
        "is_abonne": bool(current_user.is_abonne),
        "premium_since": current_user.premium_since,
        "expires_at": expires_at,
    }

@router.post("/me/subscribe")
def subscribe(current_user: models.Utilisateur = Depends(get_current_user),
              db: Session = Depends(get_db)):
    # démarre/relance 30 jours dès maintenant
    current_user.is_abonne = True
    current_user.premium_since = datetime.now(timezone.utc)
    db.add(current_user); db.commit(); db.refresh(current_user)
    active, exp = _subscription_info(current_user)
    return {"ok": True, "is_active": active, "is_abonne": True, "premium_since": current_user.premium_since, "expires_at": exp}

@router.post("/me/unsubscribe")
def unsubscribe(current_user: models.Utilisateur = Depends(get_current_user),
                db: Session = Depends(get_db)):
    current_user.is_abonne = False
    current_user.premium_since = None
    db.add(current_user); db.commit(); db.refresh(current_user)
    return {"ok": True, "is_active": False, "is_abonne": False, "premium_since": None, "expires_at": None}



