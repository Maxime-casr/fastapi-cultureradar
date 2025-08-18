from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import ping, evenements, utilisateurs, login,organizer,participations, weather, evenements_context
from app.database import engine
from app import models

# Création de l'app
app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Création des tables
models.Base.metadata.create_all(bind=engine)

# Inclusion des routes
app.include_router(ping.router)
app.include_router(evenements.router)
app.include_router(utilisateurs.router)
app.include_router(login.router)
app.include_router(organizer.router)
app.include_router(participations.router)
app.include_router(weather.router)
app.include_router(evenements_context.router)
