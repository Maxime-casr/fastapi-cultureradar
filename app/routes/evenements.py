from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models, schemas

router = APIRouter(prefix="/evenements", tags=["Evenements"])

# Permet d'ouvrir une session DB pour chaque requête
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.EvenementResponse)
def create_evenement(evenement: schemas.EvenementCreate, db: Session = Depends(get_db)):
    db_event = models.Evenement(**evenement.dict())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@router.get("/", response_model=list[schemas.EvenementResponse])
def read_evenements(limit: int = Query(default=10), offset: int = Query(default=0), db: Session = Depends(get_db)):
    return db.query(models.Evenement).offset(offset).limit(limit).all()

@router.get("/search", response_model=list[schemas.EvenementResponse])
def search_evenements(q: str = "", db: Session = Depends(get_db)):
    return db.query(models.Evenement).filter(models.Evenement.titre.ilike(f"%{q}%")).all()

@router.get("/{event_id}", response_model=schemas.EvenementResponse)
def get_evenement_by_id(event_id: int, db: Session = Depends(get_db)):
    event = db.query(models.Evenement).filter(models.Evenement.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Événement introuvable")
    return event


