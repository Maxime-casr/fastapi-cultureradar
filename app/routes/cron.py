# app/routes/cron.py
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
import os

from app.auth import get_db
from app.tasks.daily_digest import run as run_digest

router = APIRouter(prefix="/cron", tags=["Cron"])

CRON_SECRET = os.getenv("CRON_SECRET")  # mets une valeur forte dans tes env vars

@router.post("/daily-digest")
def daily_digest(x_cron_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not CRON_SECRET or x_cron_key != CRON_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    app_public = os.getenv("APP_PUBLIC_URL", "http://localhost:4200")
    return run_digest(db, app_public)
