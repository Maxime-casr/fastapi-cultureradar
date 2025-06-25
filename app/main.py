from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import ping, evenements, utilisateurs, login
from app.database import engine
from app import models

# Création de l'app
app = FastAPI()

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins = ["http://localhost:4200"],
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
