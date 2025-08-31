# app/tasks/daily_digest.py
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from sqlalchemy.orm import Session
from app.models import Participation, Occurrence, Evenement, Utilisateur
from app.utils.email import send_email

PARIS = ZoneInfo("Europe/Paris")

def _paris_today_window_utc(now_utc: datetime | None = None):
    now_utc = now_utc or datetime.now(timezone.utc)
    today_local = now_utc.astimezone(PARIS).date()
    start_local = datetime.combine(today_local, time(0, 0), tzinfo=PARIS)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), today_local

def _fmt_local(dt: datetime) -> str:
    # gère naïf/aware (on considère naïf = UTC en base)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_local = dt.astimezone(PARIS)
    return "Toute la journée" if dt_local.hour == 0 and dt_local.minute == 0 else dt_local.strftime("%H:%M")

def _build_email(user: Utilisateur, items: list[tuple[Occurrence, Evenement]], app_public_url: str) -> str:
    lis = []
    for occ, evt in items:
        when = "Toute la journée" if occ.all_day else _fmt_local(occ.debut)
        lieu = evt.lieu or evt.commune or ""
        line = f"""<li><b>{evt.titre}</b>{' — ' + when if when else ''}{' — ' + lieu if lieu else ''}<br>
                   <a href="{app_public_url}/event/{evt.id}">Voir l’événement</a></li>"""
        lis.append(line)
    return f"""
    <div style="font-family:system-ui,Segoe UI,Roboto,Arial">
      <h2>Tes événements du jour</h2>
      <p>Bonjour {user.nom or user.email}, voici un rappel pour aujourd’hui :</p>
      <ul>{''.join(lis)}</ul>
      <p style="color:#6b7280">Bonne journée !</p>
    </div>
    """

def run(db: Session, app_public_url: str) -> dict:
    start_utc, end_utc, today_local = _paris_today_window_utc()

    q = (db.query(Participation, Occurrence, Evenement, Utilisateur)
           .join(Occurrence, Participation.occurrence_id == Occurrence.id)
           .join(Evenement, Occurrence.evenement_id == Evenement.id)
           .join(Utilisateur, Participation.user_id == Utilisateur.id)
           .filter(Participation.status == "going")
           .filter(Occurrence.debut >= start_utc)
           .filter(Occurrence.debut <  end_utc)
           .order_by(Utilisateur.id, Occurrence.debut))

    rows = q.all()

    grouped: dict[int, list[tuple[Occurrence, Evenement]]] = defaultdict(list)
    users: dict[int, Utilisateur] = {}

    for part, occ, evt, user in rows:
        users[user.id] = user
        grouped[user.id].append((occ, evt))

    sent = 0
    for uid, items in grouped.items():
        user = users[uid]
        if not user.is_email_verified:
            continue
        html = _build_email(user, items, app_public_url)
        send_email(user.email, "Rappel — tes événements du jour", html)
        sent += 1

    return {"date_local": str(today_local), "users_notified": sent}
