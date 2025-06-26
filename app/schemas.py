from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class EvenementBase(BaseModel):
    titre: str
    description: str
    longdescription: str
    lieu: str
    date: datetime
    prix: float

    # Ajouts
    image_url: Optional[str]
    commune: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    conditions: Optional[str]
    age: Optional[int]
    latitude: Optional[float]
    longitude: Optional[float]

class EvenementCreate(EvenementBase):
    pass

class EvenementResponse(EvenementBase):
    id: int

    class Config:
        orm_mode = True

class UtilisateurBase(BaseModel):
    nom: str
    email: str
    musique: Optional[bool] = False
    theatre: Optional[bool] = False
    cinema: Optional[bool] = False
    expositions: Optional[bool] = False

class UtilisateurCreate(UtilisateurBase):
    mot_de_passe: str

class UtilisateurResponse(UtilisateurBase):
    id: int

    class Config:
        orm_mode = True

class UtilisateurUpdate(BaseModel):
    nom: Optional[str] = None
    email: Optional[str] = None
    musique: Optional[bool] = None
    theatre: Optional[bool] = None
    cinema: Optional[bool] = None
    expositions: Optional[bool] = None

class LoginRequest(BaseModel):
    email: str
    mot_de_passe: str

