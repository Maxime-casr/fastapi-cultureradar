# app/routes/evenements.py
from typing import List, Optional
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc, desc, or_, and_, func, case, literal, cast, Float
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

@router.get("", response_model=List[schemas.EvenementResponse])
def list_evenements(
    # texte / ville / dates
    q: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),

    # heures locales Europe/Paris (sur l'heure de début)
    hour_from: Optional[int] = Query(None, ge=0, le=23),
    hour_to:   Optional[int] = Query(None, ge=0, le=23),

    # filtre géo (rayon en km)
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: Optional[float] = Query(None, ge=0.1),

    # keywords avancés
    kw_any:  Optional[List[str]] = Query(None, description="au moins un"),
    kw_all:  Optional[List[str]] = Query(None, description="tous"),
    kw_none: Optional[List[str]] = Query(None, description="aucun"),

    # tranche d’âge
    age_min_lte: Optional[int] = Query(None),
    age_max_gte: Optional[int] = Query(None),

    # tri / pagination
    future_only: bool = Query(True),
    order: str = Query("date_asc"),
    page: Optional[int] = Query(None, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: Optional[int] = Query(None, ge=0),

    db: Session = Depends(get_db),
):
    now = datetime.utcnow()

    # pagination
    if page is not None:
        offset_val = (page - 1) * per_page
        limit_val = per_page
    else:
        offset_val = offset if offset is not None else 0
        limit_val = limit if limit is not None else per_page

    # sous-requête: première occurrence dans la fenêtre
    base_occ = db.query(
        models.Occurrence.evenement_id.label("ev_id"),
        func.min(models.Occurrence.debut).label("first_debut")
    )
    if date_from or date_to:
        start_dt = datetime.combine(date_from or date.today(), datetime.min.time())
        end_dt   = datetime.combine(date_to   or date.max,   datetime.max.time())
        base_occ = base_occ.filter(models.Occurrence.debut >= start_dt,
                                   models.Occurrence.debut <= end_dt)
    elif future_only:
        base_occ = base_occ.filter(models.Occurrence.debut >= now)

    # filtre heures locales
    if hour_from is not None and hour_to is not None:
        local_ts = func.timezone('Europe/Paris', func.timezone('UTC', models.Occurrence.debut))
        hr = func.extract("hour", local_ts)
        if hour_from <= hour_to:
            base_occ = base_occ.filter(and_(hr >= hour_from, hr <= hour_to))
        else:
            base_occ = base_occ.filter(or_(hr >= hour_from, hr <= hour_to))

    occ_sub = base_occ.group_by(models.Occurrence.evenement_id).subquery()

    qs = (
        db.query(models.Evenement)
          .join(occ_sub, occ_sub.c.ev_id == models.Evenement.id)
          .options(joinedload(models.Evenement.occurrences))
    )

    # texte
    if q:
        like = f"%{q}%"
        qs = qs.filter(
            models.Evenement.titre.ilike(like) |
            models.Evenement.description.ilike(like) |
            models.Evenement.longdescription.ilike(like) |
            models.Evenement.lieu.ilike(like) |
            models.Evenement.commune.ilike(like) |
            getattr(models.Evenement, "adresse", models.Evenement.lieu).ilike(like)
        )

    # ville (filtre textuel simple)
    if city:
        like_city = f"%{city}%"
        qs = qs.filter(
            or_(
                models.Evenement.commune.ilike(like_city),
                models.Evenement.lieu.ilike(like_city),
                getattr(models.Evenement, "adresse", models.Evenement.lieu).ilike(like_city),
            )
        )

    # normalisation kw identique à l’import
    import unicodedata
    def _norm_kw(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "")
        s = "".join(c for c in s if not unicodedata.combining(c))
        return s.strip().lower()

    # kw_all: doit contenir tous
    if kw_all:
        kws = [_norm_kw(x) for x in kw_all if x]
        if kws:
            qs = qs.filter(models.Evenement.keywords.contains(kws))

    # kw_any: au moins un
    if kw_any:
        cond = None
        for k in ([_norm_kw(x) for x in kw_any if x] or []):
            clause = models.Evenement.keywords.contains([k])
            cond = clause if cond is None else (cond | clause)
        if cond is not None:
            qs = qs.filter(cond)

    # kw_none: exclure
    if kw_none:
        for k in ([_norm_kw(x) for x in kw_none if x] or []):
            qs = qs.filter(~models.Evenement.keywords.contains([k]))

    # âge
    if age_min_lte is not None:
        qs = qs.filter((models.Evenement.age_min == None) | (models.Evenement.age_min <= age_min_lte))
    if age_max_gte is not None:
        qs = qs.filter((models.Evenement.age_max == None) | (models.Evenement.age_max >= age_max_gte))

    # distance (si lat/lon)
    # distance (si lat/lon)
    if lat is not None and lon is not None:
        radius = float(radius_km or 50.0)  # défaut 50 km

        # BBOX rapide (côté Python)
        delta_lat = radius / 111.0
        denom = max(0.00001, math.cos(math.radians(lat)) * 111.0)
        delta_lon = radius / denom

        qs = qs.filter(
            models.Evenement.latitude.isnot(None),
            models.Evenement.longitude.isnot(None),
            models.Evenement.latitude.between(lat - delta_lat, lat + delta_lat),
            models.Evenement.longitude.between(lon - delta_lon, lon + delta_lon),
        )

        # Haversine précis (côté SQL) pour couper tout ce qui est hors rayon
        R = 6371.0
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        lat2 = func.radians(cast(models.Evenement.latitude, Float))
        lon2 = func.radians(cast(models.Evenement.longitude, Float))

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        # clamp numérique et distance
        a = (func.pow(func.sin(dlat/2.0), 2) +
            math.cos(lat1) * func.cos(lat2) * func.pow(func.sin(dlon/2.0), 2))
        a_clamped = func.least(literal(1.0), func.greatest(literal(0.0), a))
        distance_km = 2.0 * R * func.asin(func.sqrt(a_clamped))

        qs = qs.filter(distance_km <= radius)

    # tri
    qs = qs.order_by(occ_sub.c.first_debut.desc().nulls_last() if order == "date_desc"
                     else occ_sub.c.first_debut.asc().nulls_last())

    return qs.offset(offset_val).limit(limit_val).all()

# ---------- HOME 
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

@router.get("/reco", response_model=List[schemas.EvenementResponse])
def recommended_events(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    now = datetime.utcnow()

    # 1) prefs mots-clés (TOP N)
    top_prefs = (
        db.query(models.UserKeywordPref)
          .filter(models.UserKeywordPref.user_id == me.id)
          .order_by(models.UserKeywordPref.score.desc(),
                    models.UserKeywordPref.updated_at.desc())
          .limit(20)
          .all()
    )

    # normaliser les poids pour éviter l’explosion
    total_weight = sum((p.score or 1) for p in top_prefs) or 1
    score_expr = literal(0, type_=Float)
    for pref in top_prefs:
        w = (pref.score or 1) / total_weight  # normalisation
        score_expr = score_expr + case(
            (models.Evenement.keywords.contains([pref.keyword]), w),
            else_=0.0
        )

    # 2) prochaine occurrence
    next_occ = (
        db.query(models.Occurrence.evenement_id,
                 func.min(models.Occurrence.debut).label("next_debut"))
        .filter(models.Occurrence.debut >= now)
        .group_by(models.Occurrence.evenement_id)
        .subquery()
    )

    qs = (
        db.query(models.Evenement, next_occ.c.next_debut)
          .join(next_occ, next_occ.c.evenement_id == models.Evenement.id)
    )

    # 3) exclure events déjà "going"
    going_ev_ids = (
        db.query(models.Occurrence.evenement_id)
          .join(models.Participation, models.Participation.occurrence_id == models.Occurrence.id)
          .filter(models.Participation.user_id == me.id,
                  models.Participation.status == "going")
          .subquery()
    )
    qs = qs.filter(~models.Evenement.id.in_(going_ev_ids))

    # 4) âge user vs age_min/max
    if getattr(me, "age", None) is not None:
        qs = qs.filter(
            or_(models.Evenement.age_min == None, models.Evenement.age_min <= me.age),
            or_(models.Evenement.age_max == None, models.Evenement.age_max >= me.age),
        )

    # 5) créneau & jour en Europe/Paris
    # next_debut est un "timestamp without tz" UTC -> converti vers Europe/Paris
    # (ts AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Paris' renvoie un timestamp local sans tz
    local_ts = func.timezone('Europe/Paris', func.timezone('UTC', next_occ.c.next_debut))
    dow_expr = func.extract("dow", local_ts)   # 0=dimanche ... 6=samedi
    hr_expr  = func.extract("hour", local_ts)

    day_bonus = literal(0.0)
    day_map = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    wanted_days = [day_map[d] for d in (me.available_days or []) if d in day_map]
    if wanted_days:
        day_bonus = case((dow_expr.in_(wanted_days), 1.0), else_=0.0)

    slot_bonus = literal(0.0)
    slot = getattr(me, "preferred_slot", None)
    if slot:
        if slot == "morning":      cond = and_(hr_expr >= 6,  hr_expr <= 11)
        elif slot == "afternoon":  cond = and_(hr_expr >= 12, hr_expr <= 17)
        elif slot == "evening":    cond = and_(hr_expr >= 18, hr_expr <= 22)
        else:                      cond = or_(hr_expr >= 23, hr_expr < 6)  # night
        slot_bonus = case((cond, 1.0), else_=0.0)

    # 6) distance score (bbox + haversine)
    distance_km_expr = literal(None, type_=Float)
    distance_score   = literal(0.0)

    ctx = (
        db.query(models.UserContext)
          .filter(models.UserContext.user_id == me.id)
          .first()
    )
    if ctx and ctx.home_lat is not None and ctx.home_lon is not None and getattr(me, "mobility", None):
        radius_by_mode = {"walk": 2.0, "bike": 8.0, "car": 40.0}
        radius = radius_by_mode.get(me.mobility, 40.0)

        # bbox rapide
        delta_lat = radius / 111.0
        denom = max(0.00001, math.cos(math.radians(ctx.home_lat)) * 111.0)
        delta_lon = radius / denom

        qs = qs.filter(
            models.Evenement.latitude.isnot(None),
            models.Evenement.longitude.isnot(None),
            models.Evenement.latitude.between(ctx.home_lat - delta_lat, ctx.home_lat + delta_lat),
            models.Evenement.longitude.between(ctx.home_lon - delta_lon, ctx.home_lon + delta_lon),
        )

        # haversine (Postgres a sin/cos/acos/radians)
        # 2*R*asin(sqrt(a)), mais on peut approx avec acos; restons haversine robuste:
        lat1 = func.radians(literal(ctx.home_lat))
        lon1 = func.radians(literal(ctx.home_lon))
        lat2 = func.radians(cast(models.Evenement.latitude, Float))
        lon2 = func.radians(cast(models.Evenement.longitude, Float))

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (func.power(func.sin(dlat/2.0), 2) +
             func.cos(lat1) * func.cos(lat2) * func.power(func.sin(dlon/2.0), 2))
        # clamp numérique
        a_clamped = func.least(literal(1.0), func.greatest(literal(0.0), a))
        earth_km = 6371.0
        distance_km_expr = 2.0 * earth_km * func.asin(func.sqrt(a_clamped))

        # score [0..1] = max(0, 1 - d/radius)
        distance_score = func.greatest(0.0, 1.0 - (distance_km_expr / radius))

    # 7) time decay (plus c’est proche, mieux c’est)
    # days_to = (next_debut - now)/86400 ; decay = exp(-lambda * days), lambda ~ 0.15 (≈ demi-vie ~ 4.6 j)
    seconds_to = (func.extract('epoch', next_occ.c.next_debut) - func.extract('epoch', literal(now)))  # en s
    days_to = seconds_to / 86400.0
    decay = func.exp(-0.15 * func.greatest(0.0, days_to))  # [~0..1]

    # 8) ratings (moyenne + volume, façon "shrinkage")
    rating_cte = (
        db.query(
            models.EventRating.evenement_id.label("ev_id"),
            func.avg(models.EventRating.rating).label("avg"),
            func.count(models.EventRating.id).label("cnt"),
        )
        .group_by(models.EventRating.evenement_id)
        .cte("rating_stats")
    )
    qs = qs.outerjoin(rating_cte, rating_cte.c.ev_id == models.Evenement.id)

    # score_rating = (cnt/(cnt+10)) * (avg/5)
    score_rating = (
        (func.coalesce(rating_cte.c.cnt, 0.0) / (func.coalesce(rating_cte.c.cnt, 0.0) + 10.0))
        * (func.coalesce(rating_cte.c.avg, 0.0) / 5.0)
    )

    # 9) score global (poids à ajuster)
    W_PREF, W_DAY, W_SLOT, W_DIST, W_TIME, W_RATE = 3.0, 1.5, 1.5, 2.0, 2.0, 1.5
    total_score = (
        (score_expr * W_PREF)
        + (day_bonus * W_DAY)
        + (slot_bonus * W_SLOT)
        + (distance_score * W_DIST)
        + (decay * W_TIME)
        + (score_rating * W_RATE)
    )

    rows = (
        qs.options(joinedload(models.Evenement.occurrences))
          .order_by(desc(total_score), asc(next_occ.c.next_debut))
          .offset(offset).limit(limit)
          .all()
    )
    # rows = [(Evenement, next_debut), ...] -> ne retourner que Evenement
    return [r[0] for r in rows]

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
    return schemas.RatingMyOut(rating=r.rating, commentaire=r.commentaire)  # <-- ajouté



@router.put("/{event_id}/ratings", response_model=schemas.RatingAverage)
def upsert_my_event_rating(
    event_id: int,
    payload: schemas.RatingSet,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    # ⬅️ plus de vérification "événement passé + participation"
    # Seule l'authentification est requise.

    existing = (
        db.query(models.EventRating)
          .filter(models.EventRating.user_id == me.id,
                  models.EventRating.evenement_id == event_id)
          .first()
    )
    if existing:
        existing.rating = int(payload.rating)
        existing.commentaire = payload.commentaire
        existing.updated_at = datetime.utcnow()
    else:
        db.add(models.EventRating(
            user_id=me.id,
            evenement_id=event_id,
            rating=int(payload.rating),
            commentaire=payload.commentaire,
        ))
    db.commit()

    row = (
        db.query(func.avg(models.EventRating.rating).label("avg"),
                 func.count(models.EventRating.id))
          .filter(models.EventRating.evenement_id == event_id)
          .one()
    )
    avg = float(row[0]) if row[0] is not None else None
    count = int(row[1] or 0)
    return schemas.RatingAverage(average=round(avg, 3) if avg is not None else None, count=count)


@router.get("/{event_id}/ratings", response_model=List[schemas.RatingPublicOut])
def list_event_reviews(
    event_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    include_empty: bool = Query(False, description="Inclure aussi les notes sans commentaire"),
    db: Session = Depends(get_db),
):
    """
    Retourne les avis (commentaire + note) d'un événement, avec le nom de l'utilisateur.
    - Par défaut: uniquement les avis ayant un commentaire non vide.
    - Tri: du plus récent au plus ancien.
    - Pagination: page/per_page.
    """

    # Vérifier existence de l'événement (optionnel mais propre)
    exists = db.query(models.Evenement.id).filter(models.Evenement.id == event_id).first()
    if not exists:
        raise HTTPException(404, "Événement introuvable")

    q = (
        db.query(
            models.EventRating.id.label("id"),
            models.EventRating.user_id.label("user_id"),
            models.Utilisateur.nom.label("user_nom"),
            models.EventRating.rating.label("rating"),
            models.EventRating.commentaire.label("commentaire"),
            models.EventRating.created_at.label("created_at"),
        )
        .join(models.Utilisateur, models.Utilisateur.id == models.EventRating.user_id)
        .filter(models.EventRating.evenement_id == event_id)
    )

    if not include_empty:
        # seulement les avis avec un commentaire non nul et non vide
        q = q.filter(
            models.EventRating.commentaire.isnot(None),
            func.length(func.trim(models.EventRating.commentaire)) > 0
        )

    # Tri du plus récent au plus ancien
    q = q.order_by(models.EventRating.created_at.desc())

    # Pagination
    offset = (page - 1) * per_page
    rows = q.offset(offset).limit(per_page).all()

    # On retourne une liste de dicts prêts pour Pydantic
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "user_nom": r.user_nom,
            "rating": r.rating,
            "commentaire": r.commentaire,
            "created_at": r.created_at,
        }
        for r in rows
    ]

@router.get("/{event_id}/ratings/counts")
def count_event_reviews(
    event_id: int,
    db: Session = Depends(get_db),
):
    total = (
        db.query(func.count(models.EventRating.id))
          .filter(models.EventRating.evenement_id == event_id)
          .scalar()
    )
    total_with_comments = (
        db.query(func.count(models.EventRating.id))
          .filter(
              models.EventRating.evenement_id == event_id,
              models.EventRating.commentaire.isnot(None),
              func.length(func.trim(models.EventRating.commentaire)) > 0
          )
          .scalar()
    )
    return {"total": int(total or 0), "total_with_comments": int(total_with_comments or 0)}


