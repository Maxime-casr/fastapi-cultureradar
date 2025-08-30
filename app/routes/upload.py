# app/routes/upload.py
from fastapi import APIRouter, UploadFile, File, HTTPException
import uuid, os

router = APIRouter(prefix="/upload", tags=["Upload"])

UPLOAD_DIR = "uploads"

@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Fichier image attendu")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(await file.read())
    # retourne une URL (à adapter selon ton hébergeur)
    return {"url": f"/static/uploads/{fname}"}
