# app/import_openagenda.py
import os
import requests
from sqlalchemy.orm import Session
from dateutil.parser import parse
from dotenv import load_dotenv

from app.database import SessionLocal
from app.models import Evenement, Occurrence

load_dotenv()

API_KEY = os.getenv("OPENAGENDA_API_KEY")
AGENDA_SLUG = "ile-de-france"

def _as_fr_list_keywords(kw_obj) -> list[str] | None:
    """
    OpenAgenda renvoie souvent keywords comme objet multilingue:
    { "fr": ["musique","rock"], "en": ["music","rock"] }
    On normalise en simple liste FR si dispo, sinon on rabat sur liste brute.
    """
    if not kw_obj:
        return None
    if isinstance(kw_obj, dict):
        if kw_obj.get("fr"):
            return [str(x) for x in kw_obj.get("fr") if x]
        # fallback: concat de toutes les langues uniques
        acc = []
        for arr in kw_obj.values():
            if isinstance(arr, list):
                acc.extend([str(x) for x in arr if x])
        return list(dict.fromkeys(acc)) or None
    if isinstance(kw_obj, list):
        return [str(x) for x in kw_obj if x] or None
    return None

def fetch_openagenda_events():
    url = f"https://api.openagenda.com/v2/agendas/{AGENDA_SLUG}/events"
    events, limit, offset = [], 100, 0
    MAX_EVENTS = 1000
    while True:
        params = {
            "key": API_KEY,
            "limit": limit,
            "offset": offset,
            "timezone": "Europe/Paris",
            "detailed": 1,
            "startsAfter": "2024-01-01",
        }
        data = requests.get(url, params=params).json()
        page = data.get("events", [])
        if not page:
            break
        events.extend(page)
        offset += limit
        if len(page) < limit or len(events) >= MAX_EVENTS:
            break
    return events

def save_events(events):
    db: Session = SessionLocal()

    # reset complet (optionnel)
    db.query(Occurrence).delete()
    db.query(Evenement).delete()
    db.commit()

    added = 0
    for ev in events:
        try:
            titre = ((ev.get("title") or {}).get("fr")) or "Sans titre"
            description = ((ev.get("description") or {}).get("fr")) or ""
            longdescription = ((ev.get("longDescription") or {}).get("fr")) or ""
            image_url = (ev.get("image") or {}).get("filename")
            contact_email = (ev.get("contact") or {}).get("email")
            contact_phone = (ev.get("contact") or {}).get("phone")

            # --- location OA ---
            loc = ev.get("location") or {}
            label = loc.get("label")
            if isinstance(label, dict):
                lieu = label.get("fr") or label.get("en") or None
            else:
                lieu = label or None

            adresse = loc.get("address") or None
            code_postal = loc.get("postalCode") or loc.get("zip") or None
            commune = loc.get("city") or None
            pays = loc.get("country") or None
            pays_code = loc.get("countryCode") or None
            latitude = loc.get("latitude")
            longitude = loc.get("longitude")

            # --- conditions / audience / status ---
            cond = ev.get("conditions")
            conditions = (cond.get("fr") if isinstance(cond, dict) else cond) or ""

            # audience: OA peut fournir un objet {"min": x, "max": y} selon config
            audience = ev.get("age") or ev.get("audience") or {}
            # On mappe vers age_min/age_max, sans forcer si absent
            age_min = audience.get("min") if isinstance(audience, dict) else None
            age_max = audience.get("max") if isinstance(audience, dict) else None

            attendance_mode = ev.get("attendanceMode")  # 1..3
            status = ev.get("status")                   # ex: 1..6 (annulé, complet, ...)

            # accessibilité: objet de drapeaux
            accessibility = ev.get("accessibility") or None

            keywords = _as_fr_list_keywords(ev.get("keywords"))

            # --- insert evenement ---
            db_ev = Evenement(
                titre=titre,
                description=description,
                longdescription=longdescription,
                image_url=image_url,
                contact_email=contact_email,
                contact_phone=contact_phone,
                conditions=conditions,

                # facettes OA normalisées
                keywords=keywords,
                attendance_mode=attendance_mode,
                status=status,
                age_min=age_min,
                age_max=age_max,
                accessibility=accessibility,

                # localisation
                lieu=lieu,
                adresse=adresse,
                code_postal=code_postal,
                commune=commune,
                pays=pays,
                pays_code=pays_code,
                latitude=latitude,
                longitude=longitude,
            )
            db.add(db_ev)
            db.flush()

            # --- occurrences ---
            for t in (ev.get("timings") or []):
                begin = t.get("begin")
                if not begin:
                    continue
                end = t.get("end")
                db.add(Occurrence(
                    evenement_id=db_ev.id,
                    debut=parse(begin),
                    fin=parse(end) if end else None,
                    all_day=bool(t.get("allDay") or False),
                ))

            added += 1

        except Exception as e:
            print("Erreur import:", e)

    db.commit()
    db.close()
    print(f"✅ Import terminé : {added} événements créés avec occurrences.")

if __name__ == "__main__":
    events = fetch_openagenda_events()
    print(f"{len(events)} événements récupérés depuis OpenAgenda.")
    save_events(events)
