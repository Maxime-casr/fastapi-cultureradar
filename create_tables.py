from app.database import engine
from app.models import Base

Base.metadata.drop_all(bind=engine)  # Supprime toutes les tables
Base.metadata.create_all(bind=engine)  # Recrée avec les nouvelles colonnes

print("✅ Tables créées avec succès !")
