# app/routes/organizer.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import SessionLocal
from app import models, schemas
from app.auth import require_organizer

router = APIRouter(prefix="/organizer", tags=["Organisateur"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/events", response_model=list[schemas.EvenementResponse])
def list_my_events(db: Session = Depends(get_db),
                   me: models.Utilisateur = Depends(require_organizer)):
    from sqlalchemy import func
    sub = (db.query(models.Occurrence.evenement_id,
                    func.min(models.Occurrence.debut).label("first_debut"))
             .group_by(models.Occurrence.evenement_id)
             .subquery())
    return (db.query(models.Evenement)
              .join(sub, sub.c.evenement_id == models.Evenement.id)
              .filter(models.Evenement.owner_id == me.id)
              .order_by(sub.c.first_debut.asc())
              .all())

@router.post("/events", response_model=schemas.EvenementResponse, status_code=201)
def create_event(body: schemas.EvenementCreate,
                 db: Session = Depends(get_db),
                 me: models.Utilisateur = Depends(require_organizer)):
    ev = models.Evenement(**body.model_dump(exclude={"occurrences"}), owner_id=me.id)
    db.add(ev); db.flush()
    for occ in (body.occurrences or []):
        db.add(models.Occurrence(
            evenement_id=ev.id,
            debut=occ.debut,
            fin=occ.fin,
            all_day=occ.all_day,
        ))
    db.commit(); db.refresh(ev)
    return ev



@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: int,
                 db: Session = Depends(get_db),
                 me: models.Utilisateur = Depends(require_organizer)):
    ev = (db.query(models.Evenement)
            .filter(models.Evenement.id == event_id,
                    models.Evenement.owner_id == me.id)
            .first())
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    db.delete(ev); db.commit()

