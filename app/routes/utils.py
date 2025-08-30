# app/routes/utils.py
from fastapi import APIRouter, HTTPException, Query
import requests

router = APIRouter(prefix="/utils", tags=["Utils"])

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
