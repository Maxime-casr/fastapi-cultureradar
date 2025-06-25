from app.database import engine
from app.models import Base

# Création des tables dans la base de données
Base.metadata.create_all(bind=engine)

print("✅ Tables créées avec succès !")
