# app/routes/utils.py
from fastapi import APIRouter, HTTPException, Query
import requests
from pydantic import BaseModel, EmailStr
from app.utils.email import send_email
import os

router = APIRouter(prefix="/utils", tags=["Utils"])
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "contact@cultureradar.fr")

class ContactIn(BaseModel):
    name: str
    email: EmailStr
    subject: str = "(Sans objet)"
    message: str
    website: str | None = None  # champ honeypot

@router.get("/geocode")
def geocode(q: str = Query(..., min_length=3)):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "limit": 1}
    headers = {"User-Agent": "CultureRadar/1.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=6)
        r.raise_for_status()
        data = r.json()
        if not data:
            raise HTTPException(404, "Adresse introuvable")
        item = data[0]
        return {"lat": float(item["lat"]), "lon": float(item["lon"])}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502, "Service de géocodage indisponible")
    


@router.post("/contact")
def contact_form(payload: ContactIn):
    # anti-spam basique
    if payload.website:
        return {"ok": True}

    try:
        html = f"""
        <div style="font-family:system-ui,Roboto,Arial">
          <h2>Nouveau message de contact</h2>
          <p><b>Nom:</b> {payload.name}</p>
          <p><b>Email:</b> {payload.email}</p>
          <p><b>Objet:</b> {payload.subject}</p>
          <p style="white-space:pre-line">{payload.message}</p>
        </div>
        """
        send_email(CONTACT_EMAIL, f"[Contact] {payload.subject}", html)
        return {"ok": True}
    except Exception:
        raise HTTPException(status_code=500, detail="Impossible d’envoyer l’email")
