# app/routes/weather.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.weather_client import fetch_and_cache_weather

router = APIRouter(prefix="/weather", tags=["Weather"])

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("")
async def get_weather(lat: float = Query(..., ge=-90, le=90),
                      lon: float = Query(..., ge=-180, le=180),
                      db: Session = Depends(get_db)):
    try:
        row = await fetch_and_cache_weather(db, lat, lon)
    except Exception as e:
        raise HTTPException(502, f"Weather provider error: {e}")
    return {
        "lat": row.lat, "lon": row.lon, "ts_hour": row.ts_hour,
        "temp_c": row.temp_c, "rain_mm": row.rain_mm,
        "wind_kph": row.wind_kph, "precip_prob": row.precip_prob,
        "is_rainy": row.is_rainy, "is_hot": row.is_hot, "is_cold": row.is_cold
    }
