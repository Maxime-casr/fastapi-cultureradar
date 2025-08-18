# app/routes/evenements.py
from typing import List, Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc, desc, or_, and_, func, case, literal, cast
import math


from app.database import SessionLocal
from app import models, schemas
from app.auth import get_current_user  # nécessaire pour /reco

router = APIRouter(prefix="/evenements", tags=["Evenements"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/", response_model=schemas.EvenementResponse)
def create_evenement(evenement: schemas.EvenementCreate, db: Session = Depends(get_db)):
    ev = models.Evenement(**evenement.model_dump(exclude={"occurrences"}))
    db.add(ev)
    db.flush()  # pour avoir ev.id
    for occ in (evenement.occurrences or []):
        db.add(models.Occurrence(
            evenement_id=ev.id,
            debut=occ.debut,
            fin=occ.fin,
            all_day=occ.all_day,
        ))
    db.commit()
    db.refresh(ev)
    return ev

# ---------- LISTE / RECHERCHE ----------
@router.get("", response_model=List[schemas.EvenementResponse])
def list_evenements(
    q: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    future_only: bool = Query(True),
    order: str = Query("date_asc"),

    # facettes OA
    keyword: Optional[List[str]] = Query(None, description="répétable: ?keyword=rock&keyword=jazz"),
    online: Optional[bool] = Query(None, description="True=online/mixte, False=offline"),
    status_in: Optional[str] = Query(None, description="CSV des codes OA: '1,2,3'"),
    age_min_lte: Optional[int] = Query(None),
    age_max_gte: Optional[int] = Query(None),
    accessible: Optional[List[str]] = Query(None, description="ex: vi,hi,mi,ii,pi"),

    # pagination
    page: Optional[int] = Query(None, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: Optional[int] = Query(None, ge=0),

    db: Session = Depends(get_db),
):
    now = datetime.utcnow()

    # calcul offset/limit
    if page is not None:
        offset_val = (page - 1) * per_page
        limit_val = per_page
    else:
        offset_val = offset if offset is not None else 0
        limit_val = limit if limit is not None else per_page

    # min(debut) selon fenêtre
    base_occ = db.query(
        models.Occurrence.evenement_id.label("ev_id"),
        func.min(models.Occurrence.debut).label("first_debut")
    )
    if date_from or date_to:
        start_dt = datetime.combine(date_from or date.today(), datetime.min.time())
        end_dt = datetime.combine(date_to or date.max, datetime.max.time())
        base_occ = base_occ.filter(models.Occurrence.debut >= start_dt,
                                   models.Occurrence.debut <= end_dt)
    elif future_only:
        base_occ = base_occ.filter(models.Occurrence.debut >= now)
    occ_sub = base_occ.group_by(models.Occurrence.evenement_id).subquery()

    qs = (
        db.query(models.Evenement)
          .join(occ_sub, occ_sub.c.ev_id == models.Evenement.id)
          .options(joinedload(models.Evenement.occurrences))
    )

    # recherche plein texte
    if q:
        like = f"%{q}%"
        qs = qs.filter(
            (models.Evenement.titre.ilike(like)) |
            (models.Evenement.description.ilike(like)) |
            (models.Evenement.longdescription.ilike(like)) |
            (models.Evenement.lieu.ilike(like)) |
            (models.Evenement.commune.ilike(like)) |
            (getattr(models.Evenement, "adresse", models.Evenement.lieu).ilike(like))
        )

    # ville
    if city:
        like_city = f"%{city}%"
        qs = qs.filter(
            or_(
                models.Evenement.commune.ilike(like_city),
                models.Evenement.lieu.ilike(like_city),
                getattr(models.Evenement, "adresse", models.Evenement.lieu).ilike(like_city),
            )
        )

    # keywords (Postgres JSONB)
    if keyword:
        cond = None
        for k in keyword:
            if not k:
                continue
            clause = models.Evenement.keywords.contains([k])
            cond = clause if cond is None else (cond | clause)
        if cond is not None:
            qs = qs.filter(cond)

    # online/offline
    if online is not None:
        if online:
            qs = qs.filter(models.Evenement.attendance_mode.in_([2, 3]))
        else:
            qs = qs.filter(models.Evenement.attendance_mode == 1)

    # status CSV
    if status_in:
        try:
            codes = [int(x.strip()) for x in status_in.split(",") if x.strip()]
            if codes:
                qs = qs.filter(models.Evenement.status.in_(codes))
        except ValueError:
            pass

    # âge
    if age_min_lte is not None:
        qs = qs.filter((models.Evenement.age_min == None) | (models.Evenement.age_min <= age_min_lte))
    if age_max_gte is not None:
        qs = qs.filter((models.Evenement.age_max == None) | (models.Evenement.age_max >= age_max_gte))

    # accessibilité (Postgres JSONB)
    if accessible:
        for code in accessible:
            qs = qs.filter(models.Evenement.accessibility[code].astext == 'true')

    # tri
    if order == "date_desc":
        qs = qs.order_by(occ_sub.c.first_debut.desc().nulls_last())
    else:
        qs = qs.order_by(occ_sub.c.first_debut.asc().nulls_last())

    return qs.offset(offset_val).limit(limit_val).all()

# ---------- HOME (fixe) ----------
@router.get("/home", response_model=List[schemas.EvenementResponse])
def home_events(limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    now = datetime.utcnow()
    next_occ = (
        db.query(models.Occurrence.evenement_id, func.min(models.Occurrence.debut).label("next_debut"))
        .filter(models.Occurrence.debut >= now)
        .group_by(models.Occurrence.evenement_id)
        .subquery()
    )
    return (
        db.query(models.Evenement)
          .join(next_occ, next_occ.c.evenement_id == models.Evenement.id)
          .options(joinedload(models.Evenement.occurrences))
          .order_by(next_occ.c.next_debut.asc())
          .offset(offset).limit(limit)
          .all()
    )

# ---------- RECO 
@router.get("/reco", response_model=List[schemas.EvenementResponse])
def recommended_events(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    """
    Recommandations = combinaison de :
      - préférences par mots-clés (UserKeywordPref)
      - adéquation jour de la semaine (available_days)
      - adéquation créneau horaire (preferred_slot)
      - filtrage par âge (age_min/age_max)
      - filtrage géographique selon mobilité + home_lat/lon (UserContext)
    """
    now = datetime.utcnow()


    top_prefs = (
        db.query(models.UserKeywordPref)
          .filter(models.UserKeywordPref.user_id == me.id)
          .order_by(models.UserKeywordPref.score.desc(), models.UserKeywordPref.updated_at.desc())
          .limit(20)
          .all()
    )

    score_expr = None
    if top_prefs:
        for pref in top_prefs:
            kw = pref.keyword
            weight = pref.score or 1
            clause = case((models.Evenement.keywords.contains([kw]), weight), else_=0)
            score_expr = clause if score_expr is None else (score_expr + clause)
    else:
        score_expr = literal(0)

  
    next_occ = (
        db.query(models.Occurrence.evenement_id, func.min(models.Occurrence.debut).label("next_debut"))
        .filter(models.Occurrence.debut >= now)
        .group_by(models.Occurrence.evenement_id)
        .subquery()
    )

    qs = (
        db.query(models.Evenement)
          .join(next_occ, next_occ.c.evenement_id == models.Evenement.id)
          .options(joinedload(models.Evenement.occurrences))
    )

   
    if getattr(me, "age", None) is not None:
        qs = qs.filter(
            or_(models.Evenement.age_min == None, models.Evenement.age_min <= me.age),
            or_(models.Evenement.age_max == None, models.Evenement.age_max >= me.age),
        )


    ctx = (
        db.query(models.UserContext)
          .filter(models.UserContext.user_id == me.id)
          .first()
    )
    if ctx and ctx.home_lat is not None and ctx.home_lon is not None and getattr(me, "mobility", None):
        radius_by_mode = {"walk": 2.0, "bike": 8.0, "car": 40.0}
        radius_km = radius_by_mode.get(me.mobility, 40.0)

    
        delta_lat = radius_km / 111.0
        denom = max(0.00001, math.cos(math.radians(ctx.home_lat)) * 111.0)
        delta_lon = radius_km / denom

        qs = qs.filter(
            models.Evenement.latitude != None,
            models.Evenement.longitude != None,
            models.Evenement.latitude.between(ctx.home_lat - delta_lat, ctx.home_lat + delta_lat),
            models.Evenement.longitude.between(ctx.home_lon - delta_lon, ctx.home_lon + delta_lon),
        )

   
    dow_expr = func.extract("dow", next_occ.c.next_debut)  
    hr_expr  = func.extract("hour", next_occ.c.next_debut)

    
    day_bonus = literal(0)
    day_map = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    wanted_days = [day_map[d] for d in (me.available_days or []) if d in day_map]
    if wanted_days:
        day_bonus = case((dow_expr.in_(wanted_days), 1), else_=0)  

    
    slot_bonus = literal(0)
    slot = getattr(me, "preferred_slot", None)
    if slot:
        if slot == "morning":     
            cond = and_(hr_expr >= 6, hr_expr <= 11)
        elif slot == "afternoon":
            cond = and_(hr_expr >= 12, hr_expr <= 17)
        elif slot == "evening":  
            cond = and_(hr_expr >= 18, hr_expr <= 22)
        else:                     
            cond = or_(hr_expr >= 23, hr_expr < 6)
        slot_bonus = case((cond, 1), else_=0)  # +1 si le créneau match

    
    # Poids simples
    total_score = (score_expr * 3) + (day_bonus * 2) + (slot_bonus * 2)

    return (
        qs.order_by(desc(total_score), asc(next_occ.c.next_debut))
          .offset(offset).limit(limit)
          .all()
    )

# ---------- PAR ID (paramétrique) ----------
@router.get("/{event_id}", response_model=schemas.EvenementResponse)
def get_evenement(event_id: int, db: Session = Depends(get_db)):
    ev = (
        db.query(models.Evenement)
          .options(joinedload(models.Evenement.occurrences))
          .filter(models.Evenement.id == event_id)
          .first()
    )
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    return ev

@router.get("/{event_id}/ratings/avg", response_model=schemas.RatingAverage)
def get_event_rating_average(event_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(func.avg(models.EventRating.rating).label("avg"), func.count(models.EventRating.id))
          .filter(models.EventRating.evenement_id == event_id)
          .one()
    )
    avg = float(row[0]) if row[0] is not None else None
    count = int(row[1] or 0)
    return schemas.RatingAverage(average=round(avg, 3) if avg is not None else None, count=count)


@router.get("/{event_id}/ratings/me", response_model=schemas.RatingMyOut)
def get_my_event_rating(
    event_id: int,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    r = (
        db.query(models.EventRating)
          .filter(models.EventRating.evenement_id == event_id,
                  models.EventRating.user_id == me.id)
          .first()
    )
    if not r:
        raise HTTPException(404, "Pas de note pour cet utilisateur")
    return schemas.RatingMyOut(rating=r.rating)


@router.put("/{event_id}/ratings", response_model=schemas.RatingAverage)
def upsert_my_event_rating(
    event_id: int,
    payload: schemas.RatingSet,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    """
    Règles:
    - l'utilisateur doit avoir participé (participation 'going')
    - à une occurrence de cet événement
    - dont le début est passé (UTC)
    """
    now = datetime.utcnow()

    # 1) Vérifier participation passée
    part_exists = (
        db.query(models.Participation.id)
          .join(models.Occurrence, models.Occurrence.id == models.Participation.occurrence_id)
          .filter(
              models.Participation.user_id == me.id,
              models.Participation.status == "going",
              models.Occurrence.evenement_id == event_id,
              models.Occurrence.debut < now,
          )
          .first()
    )
    if not part_exists:
        raise HTTPException(403, "Vous ne pouvez noter que des événements passés auxquels vous avez participé.")

    # 2) Upsert de la note
    existing = (
        db.query(models.EventRating)
          .filter(models.EventRating.user_id == me.id,
                  models.EventRating.evenement_id == event_id)
          .first()
    )
    if existing:
        existing.rating = int(payload.rating)
        existing.updated_at = datetime.utcnow()
    else:
        db.add(models.EventRating(
            user_id=me.id,
            evenement_id=event_id,
            rating=int(payload.rating),
        ))
    db.commit()

    row = (
        db.query(func.avg(models.EventRating.rating).label("avg"), func.count(models.EventRating.id))
          .filter(models.EventRating.evenement_id == event_id)
          .one()
    )
    avg = float(row[0]) if row[0] is not None else None
    count = int(row[1] or 0)
    return schemas.RatingAverage(average=round(avg, 3) if avg is not None else None, count=count)

