# app/utils/verification.py
import secrets, hashlib
from datetime import datetime, timedelta, timezone
from app.models import EmailVerificationToken, Utilisateur

def make_verif_token(db, user: Utilisateur, validity_hours=24) -> str:
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=validity_hours)
    ))
    db.commit()
    return raw

def verification_email_html(link: str, user_name: str) -> str:
    return f"""
    <div style="font-family:system-ui,Segoe UI,Roboto,Arial">
      <h2>Confirme ton e-mail</h2>
      <p>Bonjour {user_name or ''}, clique sur le bouton pour confirmer ton adresse e-mail.</p>
      <p><a href="{link}"
            style="display:inline-block;background:#111827;color:#fff;padding:12px 18px;
                   border-radius:8px;text-decoration:none">Confirmer mon e-mail</a></p>
      <p>Ou copie ce lien :<br><a href="{link}">{link}</a></p>
      <p style="color:#6b7280">Ce lien expire dans 24h.</p>
    </div>
    """
