# app/routes/evenements_context.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, desc, asc
from datetime import datetime, timedelta
from app.database import SessionLocal
from app import models
from app.auth import get_current_user

router = APIRouter(prefix="/evenements", tags=["Evenements"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def haversine_km(lat1, lon1, lat2, lon2):
    # approx SQL-friendly: 111km/deg + cos(lat) pour la lon
    return 111.0 * func.sqrt(func.pow(lat2 - lat1, 2) + func.pow((lon2 - lon1) * func.cos(func.radians(lat1)), 2))

@router.get("/reco/context")
def recommended_events_context(
    lat: float = Query(...),
    lon: float = Query(...),
    limit: int = Query(20, ge=1, le=50),
    offset: int = 0,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user)
):
    now = datetime.utcnow()

    # 1) préférences mots-clés
    top_prefs = (db.query(models.UserKeywordPref)
                   .filter(models.UserKeywordPref.user_id == me.id)
                   .order_by(models.UserKeywordPref.score.desc(), models.UserKeywordPref.updated_at.desc())
                   .limit(20).all())

    # 2) météo (dernière ligne cache pour ce lat/lon)
    wx = (db.query(models.WeatherSnapshot)
            .filter(models.WeatherSnapshot.lat==lat, models.WeatherSnapshot.lon==lon)
            .order_by(models.WeatherSnapshot.ts_hour.desc())
            .first())
    is_rainy = bool(wx.is_rainy) if wx else False
    is_hot   = bool(wx.is_hot)   if wx else False
    is_cold  = bool(wx.is_cold)  if wx else False

    # 3) prochain créneau par event
    next_occ = (db.query(models.Occurrence.evenement_id,
                         func.min(models.Occurrence.debut).label("next_debut"))
                  .filter(models.Occurrence.debut >= now)
                  .group_by(models.Occurrence.evenement_id)
                  .subquery())

    qs = (db.query(models.Evenement)
            .join(next_occ, next_occ.c.evenement_id == models.Evenement.id)
            .options(joinedload(models.Evenement.occurrences)))

    # 4) score mots-clés
    score_kw = 0
    for pref in top_prefs:
        clause = case((models.Evenement.keywords.contains([pref.keyword]), max(1, pref.score)), else_=0)
        score_kw = clause if score_kw == 0 else (score_kw + clause)

    # 5) proximité (0..3 points sur 10 km)
    dist = haversine_km(lat, lon, models.Evenement.latitude, models.Evenement.longitude)
    score_dist = case(
        (models.Evenement.latitude.is_(None), 0.0),
        else_=(func.greatest(0.0, 10.0 - dist) / 10.0) * 3.0
    )

    # 6) météo → attendance_mode : 1 offline / 2 online / 3 mixed
    # Pluie => favorise online/mixte (+2). Beau temps => léger bonus offline (+0.5).
    score_meteo = case(
        (models.Evenement.attendance_mode.in_([2,3]), 2.0 if is_rainy else 0.3),
        else_=(0.0 if is_rainy else 0.5)
    )

    # 7) fraîcheur temporelle (prochain < 48h → +1)
    soon = case((next_occ.c.next_debut <= now + timedelta(hours=48), 1.0), else_=0.0)

    total = score_kw + score_dist + score_meteo + soon

    return (qs.order_by(desc(total), asc(next_occ.c.next_debut))
              .offset(offset).limit(limit).all())
