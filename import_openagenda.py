# app/import_openagenda.py
import os, requests
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from dateutil.parser import parse
from dotenv import load_dotenv
from app.database import SessionLocal
from app.models import Evenement, Occurrence
import unicodedata

load_dotenv()
API_KEY = os.getenv("OPENAGENDA_API_KEY")
AGENDA_SLUG = os.getenv("OPENAGENDA_SLUG", "ile-de-france")

def _as_fr_list_keywords(kw_obj):
    if not kw_obj: return None
    if isinstance(kw_obj, dict):
        if kw_obj.get("fr"): return [str(x) for x in kw_obj["fr"] if x]
        acc = []
        for arr in kw_obj.values():
            if isinstance(arr, list): acc.extend([str(x) for x in arr if x])
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
            "key": API_KEY, "limit": limit, "offset": offset,
            "timezone": "Europe/Paris", "detailed": 1, "startsAfter": "2024-01-01",
        }
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        page = data.get("events", [])
        if not page: break
        events.extend(page); offset += limit
        if len(page) < limit or len(events) >= MAX_EVENTS: break
    return events

def norm_kw(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()

def upsert_events(events):
    db: Session = SessionLocal()
    added, touched_occ = 0, 0

    for ev in events:
        try:
            # 1) clé stable OA (uid → string)
            oa_uid = str(ev.get("uid") or ev.get("id") or ev.get("uuid") or "")
            if not oa_uid:
                # fallback *vraiment* à défaut… (moins fiable)
                oa_uid = f'oa:{(ev.get("slug") or "").strip()}'

            # 2) chercher event existant
            db_ev = db.query(Evenement).filter(Evenement.external_uid == oa_uid).first()

            titre = ((ev.get("title") or {}).get("fr")) or "Sans titre"
            description = ((ev.get("description") or {}).get("fr")) or ""
            longdescription = ((ev.get("longDescription") or {}).get("fr")) or ""
            image_url = (ev.get("image") or {}).get("filename")
            contact_email = (ev.get("contact") or {}).get("email")
            contact_phone = (ev.get("contact") or {}).get("phone")

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
            latitude = loc.get("latitude"); longitude = loc.get("longitude")

            cond = ev.get("conditions"); conditions = (cond.get("fr") if isinstance(cond, dict) else cond) or ""
            audience = ev.get("age") or ev.get("audience") or {}
            age_min = audience.get("min") if isinstance(audience, dict) else None
            age_max = audience.get("max") if isinstance(audience, dict) else None

            attendance_mode = ev.get("attendanceMode")
            status = ev.get("status")
            accessibility = ev.get("accessibility") or None
            keywords_raw = _as_fr_list_keywords(ev.get("keywords"))
            keywords = [norm_kw(k) for k in (keywords_raw or []) if k] or None

            if not db_ev:
                # --- créer (ADD ONLY) ---
                db_ev = Evenement(
                    external_uid=oa_uid, source="openagenda",
                    titre=titre, description=description, longdescription=longdescription,
                    image_url=image_url, contact_email=contact_email, contact_phone=contact_phone,
                    conditions=conditions, keywords=keywords, attendance_mode=attendance_mode,
                    status=status, age_min=age_min, age_max=age_max, accessibility=accessibility,
                    lieu=lieu, adresse=adresse, code_postal=code_postal, commune=commune,
                    pays=pays, pays_code=pays_code, latitude=latitude, longitude=longitude,
                )
                db.add(db_ev); db.flush()  # pour obtenir db_ev.id
                added += 1
            else:
                # --- si tu veux STRICTEMENT "ne pas toucher", commente ce bloc ---
                # ici on fait un *update léger* des champs non critiques (optionnel)
                db_ev.description = description or db_ev.description
                db_ev.longdescription = longdescription or db_ev.longdescription
                db_ev.image_url = image_url or db_ev.image_url
                db_ev.conditions = conditions or db_ev.conditions
                db_ev.keywords = keywords or db_ev.keywords
                db_ev.attendance_mode = attendance_mode or db_ev.attendance_mode
                db_ev.status = status or db_ev.status
                db_ev.age_min = age_min if age_min is not None else db_ev.age_min
                db_ev.age_max = age_max if age_max is not None else db_ev.age_max
                if lieu: db_ev.lieu = lieu
                if adresse: db_ev.adresse = adresse
                if code_postal: db_ev.code_postal = code_postal
                if commune: db_ev.commune = commune
                if pays: db_ev.pays = pays
                if pays_code: db_ev.pays_code = pays_code
                if latitude is not None: db_ev.latitude = latitude
                if longitude is not None: db_ev.longitude = longitude

            # 3) occurrences : on ajoute celles qui n’existent pas (grâce à l’unique constraint)
            # app/import_openagenda.py
            

            # ...
            for t in (ev.get("timings") or []):
                begin = t.get("begin")
                if not begin:
                    continue
                end = t.get("end")

                stmt = pg_insert(Occurrence).values(
                    evenement_id=db_ev.id,
                    debut=parse(begin),
                    fin=parse(end) if end else None,
                    all_day=bool(t.get("allDay") or False),
                ).on_conflict_do_nothing(
                    constraint="uq_occurrence_event_time"  # nom de ta contrainte unique
                )

                res = db.execute(stmt)
                touched_occ += (res.rowcount or 0)


        except Exception as e:
            db.rollback()
            print("Erreur import:", e)


    db.commit(); db.close()
    print(f"✅ Import OA terminé : {added} nouveaux événements, {touched_occ} occurrences ajoutées.")
    return {"added_events": added, "added_occurrences": touched_occ}

if __name__ == "__main__":
    events = fetch_openagenda_events()
    print(f"{len(events)} événements récupérés depuis OpenAgenda.")
    upsert_events(events)
