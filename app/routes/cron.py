# app/routes/cron.py
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
import os
from app.auth import get_db
from import_openagenda import fetch_openagenda_events, upsert_events
from app.tasks.daily_digest import run as run_digest

router = APIRouter(prefix="/cron", tags=["Cron"])
CRON_SECRET = os.getenv("CRON_SECRET")

@router.post("/nightly")
def nightly(x_cron_key: str | None = Header(default=None),
            db: Session = Depends(get_db)):
    if not CRON_SECRET or x_cron_key != CRON_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")

    # 1) sync OA
    events = fetch_openagenda_events()
    sync_res = upsert_events(events)

    # 2) mails jour J (Europe/Paris)
    app_public = os.getenv("APP_PUBLIC_URL", "http://localhost:4200")
    digest_res = run_digest(db, app_public)

    return {"sync": sync_res, "digest": digest_res}

