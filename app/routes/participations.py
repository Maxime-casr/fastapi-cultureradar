# app/routes/participations.py
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from app.database import SessionLocal
from app.auth import get_current_user
from app import models, schemas

router = APIRouter(prefix="/me/participations", tags=["Participations"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _norm_kw(s: str) -> str:
    return (s or "").strip().lower()

def _increment_first_time_keywords(db: Session, user_id: int, event: models.Evenement):
    """
    Incrémente les compteurs de mots-clés UNIQUEMENT à la première participation
    du user à CET événement.
    """
    if not event:
        return

    
    already = (
        db.query(models.Participation)
          .join(models.Occurrence, models.Occurrence.id == models.Participation.occurrence_id)
          .filter(models.Participation.user_id == user_id,
                  models.Occurrence.evenement_id == event.id)
          .first()
    )
    if already:
        return

    kws = event.keywords or []
    if not isinstance(kws, list) or not kws:
        return

    # incrémenter chaque mot-clé
    for kw in kws:
        k = _norm_kw(kw)
        if not k:
            continue
        pref = (db.query(models.UserKeywordPref)
                  .filter(models.UserKeywordPref.user_id == user_id,
                          models.UserKeywordPref.keyword == k)
                  .first())
        if pref:
            pref.score = (pref.score or 0) + 1
        else:
            pref = models.UserKeywordPref(user_id=user_id, keyword=k, score=1)
            db.add(pref)
    

@router.get("", response_model=List[schemas.ParticipationOut])
def list_mine(
    future: bool = Query(True),
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    now = datetime.utcnow()
    q = (
        db.query(models.Participation)
          .join(models.Occurrence, models.Occurrence.id == models.Participation.occurrence_id)
          .join(models.Evenement, models.Evenement.id == models.Occurrence.evenement_id)
          .options(
              joinedload(models.Participation.occurrence)
              .joinedload(models.Occurrence.evenement)
          )
          .filter(models.Participation.user_id == me.id,
                  models.Participation.status == "going")
    )
    q = q.filter(models.Occurrence.debut >= now) if future else q.filter(models.Occurrence.debut < now)
    rows = q.order_by(models.Occurrence.debut.asc()).all()

    out: List[schemas.ParticipationOut] = []
    for p in rows:
        ev = p.occurrence.evenement
        out.append(schemas.ParticipationOut(
            id=p.id, status=p.status, created_at=p.created_at, updated_at=p.updated_at,
            occurrence_id=p.occurrence.id,
            occurrence_debut=p.occurrence.debut,
            occurrence_fin=p.occurrence.fin,
            occurrence_all_day=p.occurrence.all_day,
            evenement_id=ev.id, evenement_titre=ev.titre,
            evenement_commune=ev.commune, evenement_lieu=ev.lieu, image_url=ev.image_url,
            evenement_keywords=ev.keywords or [],
        ))
    return out

@router.post("", status_code=status.HTTP_201_CREATED, response_model=schemas.ParticipationOut)
def create_participation(
    body: schemas.ParticipationCreate,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    occ = db.query(models.Occurrence).filter(models.Occurrence.id == body.occurrence_id).first()
    if not occ:
        raise HTTPException(404, "Occurrence introuvable")

    # upsert participation
    p = (
        db.query(models.Participation)
          .filter(models.Participation.user_id == me.id,
                  models.Participation.occurrence_id == occ.id)
          .first()
    )
    if p:
        p.status = "going"
        db.add(p)
    else:
        p = models.Participation(user_id=me.id, occurrence_id=occ.id, status="going")
        db.add(p)

    # +1 mots-clés si 1re participation à cet EVÈNEMENT
    ev = db.query(models.Evenement).filter(models.Evenement.id == occ.evenement_id).first()
    _increment_first_time_keywords(db, me.id, ev)

    db.commit(); db.refresh(p)

    return schemas.ParticipationOut(
        id=p.id, status=p.status, created_at=p.created_at, updated_at=p.updated_at,
        occurrence_id=occ.id, occurrence_debut=occ.debut, occurrence_fin=occ.fin, occurrence_all_day=occ.all_day,
        evenement_id=ev.id, evenement_titre=ev.titre,
        evenement_commune=ev.commune, evenement_lieu=ev.lieu, image_url=ev.image_url,
        evenement_keywords=ev.keywords or [],
    )

@router.delete("/{participation_id}", status_code=204)
def cancel_participation(
    participation_id: int,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    p = (
        db.query(models.Participation)
          .filter(models.Participation.id == participation_id,
                  models.Participation.user_id == me.id)
          .first()
    )
    if not p:
        raise HTTPException(404, "Participation introuvable")
    p.status = "cancelled"
    db.add(p); db.commit()
