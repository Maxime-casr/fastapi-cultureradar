# app/routes/organizer.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
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
    return (db.query(models.Evenement)
              .filter(models.Evenement.owner_id == me.id)
              .order_by(models.Evenement.date.asc())
              .all())

@router.post("/events", response_model=schemas.EvenementResponse, status_code=201)
def create_event(body: schemas.EvenementCreate,
                 db: Session = Depends(get_db),
                 me: models.Utilisateur = Depends(require_organizer)):
    ev = models.Evenement(**body.model_dump(), owner_id=me.id)
    db.add(ev); db.commit(); db.refresh(ev)
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

