# app/routes/admin.py
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, desc, and_, or_

from app.database import SessionLocal
from app import models, schemas
from app.auth import get_current_user  # on s'appuie dessus

router = APIRouter(prefix="/admin", tags=["Admin"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_admin(me: models.Utilisateur = Depends(get_current_user)) -> models.Utilisateur:
    if not me or me.role != "admin":
        raise HTTPException(status_code=403, detail="Admin requis")
    return me

@router.get("/stats/overview", response_model=schemas.AdminOverview)
def admin_overview(
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(require_admin),
):
    now = datetime.utcnow()
    d7  = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    users_total = db.query(func.count(models.Utilisateur.id)).scalar() or 0
    users_new_7d = db.query(func.count(models.Utilisateur.id)).filter(models.Utilisateur.created_at >= d7).scalar() or 0
    organizers = db.query(func.count(models.Utilisateur.id)).filter(models.Utilisateur.role == "organizer").scalar() or 0
    admins     = db.query(func.count(models.Utilisateur.id)).filter(models.Utilisateur.role == "admin").scalar() or 0
    premium_active = db.query(func.count(models.Utilisateur.id)).filter(models.Utilisateur.is_abonne == True).scalar() or 0

    events_total = db.query(func.count(models.Evenement.id)).scalar() or 0

    # prochain créneau (min(debut))
    next_occ_sub = (
        db.query(models.Occurrence.evenement_id, func.min(models.Occurrence.debut).label("next_debut"))
          .group_by(models.Occurrence.evenement_id).subquery()
    )
    events_upcoming = (
        db.query(func.count(models.Evenement.id))
          .join(next_occ_sub, next_occ_sub.c.evenement_id == models.Evenement.id)
          .filter(next_occ_sub.c.next_debut >= now)
          .scalar() or 0
    )
    events_past = events_total - events_upcoming

    # complétude contenu
    with_img = db.query(func.count(models.Evenement.id)).filter(models.Evenement.image_url.isnot(None)).scalar() or 0
    with_geo = db.query(func.count(models.Evenement.id)).filter(
        models.Evenement.latitude.isnot(None), models.Evenement.longitude.isnot(None)
    ).scalar() or 0
    pct_img = round(100.0 * with_img / events_total, 1) if events_total else 0.0
    pct_geo = round(100.0 * with_geo / events_total, 1) if events_total else 0.0

    parts_total = db.query(func.count(models.Participation.id)).scalar() or 0
    parts_7d = db.query(func.count(models.Participation.id)).filter(models.Participation.created_at >= d7).scalar() or 0

    # note moyenne globale
    row = db.query(func.avg(models.EventRating.rating), func.count(models.EventRating.id)).one()
    rating_avg = float(row[0]) if row[0] is not None else None
    rating_count = int(row[1] or 0)
    rating_avg = round(rating_avg, 2) if rating_avg is not None else None

    return schemas.AdminOverview(
        users_total=users_total,
        users_new_7d=users_new_7d,
        organizers=organizers,
        admins=admins,
        premium_active=premium_active,
        events_total=events_total,
        events_upcoming=events_upcoming,
        events_past=events_past,
        events_with_image_pct=pct_img,
        events_with_geo_pct=pct_geo,
        participations_total=parts_total,
        participations_7d=parts_7d,
        rating_avg_global=rating_avg,
        ratings_count=rating_count,
    )

@router.get("/stats/time-series", response_model=schemas.AdminTimeSeries)
def admin_time_series(
    days: int = Query(30, ge=1, le=180),
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(require_admin),
):
    now = datetime.utcnow()
    since = now - timedelta(days=days)

    def daily_counts(query_col):
        rows = (
            db.query(func.date_trunc('day', query_col).label('d'),
                     func.count('*').label('c'))
              .filter(query_col >= since)
              .group_by(func.date_trunc('day', query_col))
              .order_by('d')
              .all()
        )
        return [{"date": r.d.date().isoformat(), "count": int(r.c)} for r in rows]

    # Inscrits / Participations / Notes
    users  = daily_counts(models.Utilisateur.created_at)
    parts  = daily_counts(models.Participation.created_at)
    ratings = daily_counts(models.EventRating.created_at)

    # Événements : created_at si dispo, sinon approximation via les occurrences (min: leur présence par jour)
    if hasattr(models.Evenement, "created_at"):
        events = daily_counts(models.Evenement.created_at)
    else:
        rows = (
            db.query(
                func.date_trunc('day', models.Occurrence.debut).label('d'),
                func.count(func.distinct(models.Occurrence.evenement_id)).label('c')
            )
            .filter(models.Occurrence.debut >= since)
            .group_by(func.date_trunc('day', models.Occurrence.debut))
            .order_by('d')
            .all()
        )
        events = [{"date": r.d.date().isoformat(), "count": int(r.c)} for r in rows]

    return schemas.AdminTimeSeries(
        users=users, events=events, participations=parts, ratings=ratings
    )


@router.get("/top/events", response_model=schemas.AdminTopEvents)
def admin_top_events(
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(require_admin),
):
    # Top par participations
    top_pop = (
        db.query(
            models.Evenement.id,
            models.Evenement.titre,
            models.Evenement.commune,
            models.Evenement.image_url,
            func.count(models.Participation.id).label("pcount")
        )
        .join(models.Occurrence, models.Occurrence.evenement_id == models.Evenement.id)
        .join(models.Participation, models.Participation.occurrence_id == models.Occurrence.id, isouter=True)
        .group_by(models.Evenement.id)
        .order_by(desc("pcount"))
        .limit(limit).all()
    )

    # Top par note moyenne (au moins 3 avis)
    top_rated = (
        db.query(
            models.Evenement.id,
            models.Evenement.titre,
            models.Evenement.commune,
            models.Evenement.image_url,
            func.avg(models.EventRating.rating).label("avg"),
            func.count(models.EventRating.id).label("rcount")
        )
        .join(models.EventRating, models.EventRating.evenement_id == models.Evenement.id)
        .group_by(models.Evenement.id)
        .having(func.count(models.EventRating.id) >= 3)
        .order_by(desc("avg"))
        .limit(limit).all()
    )

    return schemas.AdminTopEvents(
        most_participated=[
            schemas.AdminTopEventItem(
                id=r.id, titre=r.titre, commune=r.commune, image_url=r.image_url,
                metric=int(r.pcount or 0)
            ) for r in top_pop
        ],
        best_rated=[
            schemas.AdminTopEventItem(
                id=r.id, titre=r.titre, commune=r.commune, image_url=r.image_url,
                metric=round(float(r.avg),2)
            ) for r in top_rated
        ],
    )

@router.get("/content/quality", response_model=schemas.AdminContentQuality)
def admin_content_quality(
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(require_admin),
):
    total = db.query(func.count(models.Evenement.id)).scalar() or 0

    # image manquante (on compte aussi les vides)
    missing_img = (
        db.query(func.count(models.Evenement.id))
        .filter(or_(
            models.Evenement.image_url.is_(None),
            func.length(func.trim(models.Evenement.image_url)) == 0
        ))
        .scalar() or 0
    )


    # géoloc manquante
    missing_geo = (
        db.query(func.count(models.Evenement.id))
          .filter(or_(
              models.Evenement.latitude.is_(None),
              models.Evenement.longitude.is_(None)
          ))
          .scalar() or 0
    )

    missing_kw = (
        db.query(func.count(models.Evenement.id))
        .filter(or_(
            models.Evenement.keywords.is_(None),
            # si c'est un array -> on teste sa longueur, sinon on considère 0
            case(
                (func.jsonb_typeof(models.Evenement.keywords) == 'array',
                func.jsonb_array_length(models.Evenement.keywords)),
                else_=0
            ) == 0
        ))
        .scalar() or 0
    )

    # événements sans occurrence
    missing_occ = total - (
        db.query(func.count(func.distinct(models.Occurrence.evenement_id))).scalar() or 0
    )

    return schemas.AdminContentQuality(
        total_events=total,
        missing_image=missing_img,
        missing_geo=missing_geo,
        missing_keywords=missing_kw,
        missing_occurrences=missing_occ,
    )


def _assert_admin(me: models.Utilisateur):
    if getattr(me, "role", "user") != "admin":
        raise HTTPException(403, "Accès réservé à l’admin")

@router.get("/users", response_model=List[schemas.AdminUserRow])
def list_users(
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    _assert_admin(me)
    qs = db.query(models.Utilisateur)
    if q:
        like = f"%{q}%"
        qs = qs.filter(or_(
            models.Utilisateur.email.ilike(like),
            models.Utilisateur.nom.ilike(like),
            models.Utilisateur.role.ilike(like),
        ))
    rows = (qs.order_by(models.Utilisateur.created_at.desc())
              .offset((page-1)*per_page).limit(per_page).all())
    return rows

@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    _assert_admin(me)
    user = db.query(models.Utilisateur).get(user_id)
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")

    # Détacher la propriété des événements pour éviter la contrainte FK
    db.query(models.Evenement).filter(models.Evenement.owner_id == user_id)\
      .update({models.Evenement.owner_id: None})
    db.delete(user)
    db.commit()
    return {"ok": True}

@router.get("/events", response_model=List[schemas.AdminEventRow])
def list_events(
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    _assert_admin(me)
    now = datetime.utcnow()
    # Compte des occurrences à venir par événement
    upcoming_cte = (
        db.query(
            models.Occurrence.evenement_id.label("ev_id"),
            func.count(models.Occurrence.id).label("upcoming")
        )
        .filter(models.Occurrence.debut >= now)
        .group_by(models.Occurrence.evenement_id)
        .cte("upcoming_cte")
    )

    qs = (db.query(models.Evenement, func.coalesce(upcoming_cte.c.upcoming, 0))
            .outerjoin(upcoming_cte, upcoming_cte.c.ev_id == models.Evenement.id))

    if q:
        like = f"%{q}%"
        qs = qs.filter(or_(
            models.Evenement.titre.ilike(like),
            models.Evenement.commune.ilike(like),
            models.Evenement.lieu.ilike(like),
        ))

    rows = (qs.order_by(models.Evenement.id.desc())
              .offset((page-1)*per_page).limit(per_page).all())

    out = []
    for ev, upcoming in rows:
        out.append({
            "id": ev.id,
            "titre": ev.titre,
            "commune": ev.commune,
            "image_url": ev.image_url,
            "owner_id": ev.owner_id,
            "created_at": getattr(ev, "created_at", datetime.utcnow()),
            "upcoming": int(upcoming or 0),
        })
    return out

@router.delete("/events/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    me: models.Utilisateur = Depends(get_current_user),
):
    _assert_admin(me)
    ev = db.query(models.Evenement).get(event_id)
    if not ev:
        raise HTTPException(404, "Événement introuvable")
    db.delete(ev)  # Occurrences/ratings/participations ont ondelete('CASCADE') ou cascade ORM
    db.commit()
    return {"ok": True}
