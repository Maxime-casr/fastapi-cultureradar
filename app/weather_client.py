# app/services/weather_client.py
import math
from datetime import datetime, timezone
import httpx
from sqlalchemy.orm import Session
from app import models

OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m","precipitation","precipitation_probability","windspeed_10m"]

def _round_to_hour_utc(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

async def fetch_and_cache_weather(db: Session, lat: float, lon: float) -> models.WeatherSnapshot:
    ts = _round_to_hour_utc(datetime.now(timezone.utc))

    # cache hit ?
    row = (db.query(models.WeatherSnapshot)
             .filter(models.WeatherSnapshot.lat==lat,
                     models.WeatherSnapshot.lon==lon,
                     models.WeatherSnapshot.ts_hour==ts)
             .first())
    if row:
        return row

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY),
        "timezone": "Europe/Paris",  # pour aligner visuellement côté FR
        "forecast_days": 1,
        "models": "meteofrance_arome,meteofrance_arpege"  # hints: FR high-res where dispo
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(OPEN_METEO_ENDPOINT, params=params)
        r.raise_for_status()
        data = r.json()

    # on prend l’index correspondant à l’heure “courante” en Europe/Paris,
    # puis on enregistre la valeur (fallback index 0 si non trouvé).
    times = data.get("hourly", {}).get("time", []) or []
    try:
        now_local = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
        idx = times.index(now_local)
    except Exception:
        idx = 0 if times else None

    def pick(key, default=0):
        arr = data.get("hourly", {}).get(key, [])
        return (arr[idx] if (idx is not None and idx < len(arr)) else default)

    temp = float(pick("temperature_2m", 20.0))
    rain = float(pick("precipitation", 0.0))
    prob = int(pick("precipitation_probability", 0) or 0)
    wind = float(pick("windspeed_10m", 0.0))

    row = models.WeatherSnapshot(
        lat=lat, lon=lon, ts_hour=ts,
        temp_c=temp, rain_mm=rain, wind_kph=wind, precip_prob=prob,
        is_rainy = (rain >= 0.5 or prob >= 60),
        is_hot   = (temp >= 26),
        is_cold  = (temp <= 5)
    )
    db.add(row); db.commit(); db.refresh(row)
    return row
