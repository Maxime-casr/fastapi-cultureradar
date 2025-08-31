# app/schemas.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict, conint

DayCode = Literal['mon','tue','wed','thu','fri','sat','sun']
PreferredSlot = Literal['morning','afternoon','evening','night']
TravelMode = Literal['walk','bike','car']

class UtilisateurCreate(BaseModel):
    nom: str
    email: EmailStr
    mot_de_passe: str
    role: Optional[str] = "user"

    age: Optional[int] = None
    preferred_slot: Optional[PreferredSlot] = None
    available_days: Optional[List[DayCode]] = None
    mobility: Optional[TravelMode] = None

class LoginRequest(BaseModel):
    email: EmailStr
    mot_de_passe: str

class PreferencesSet(BaseModel):
    pref_concert: Optional[bool]    = Field(default=None, alias="concert")
    pref_exposition: Optional[bool] = Field(default=None, alias="exposition")
    pref_theatre: Optional[bool]    = Field(default=None, alias="theatre")
    pref_cinema: Optional[bool]     = Field(default=None, alias="cinema")
    pref_danse: Optional[bool]      = Field(default=None, alias="danse")
    pref_conference: Optional[bool] = Field(default=None, alias="conference")
    pref_atelier: Optional[bool]    = Field(default=None, alias="atelier")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class UtilisateurOut(BaseModel):
    id: int
    email: EmailStr
    nom: Optional[str] = None
    role: str = "user"

    created_at: Optional[datetime] = None
    age: Optional[int] = None
    preferred_slot: Optional[PreferredSlot] = None
    available_days: Optional[List[DayCode]] = None
    mobility: Optional[TravelMode] = None

    is_abonne: bool = False
    premium_since: Optional[datetime] = None
    prefs: Optional[Dict[str, bool]] = None

    model_config = ConfigDict(from_attributes=True)

class OccurrenceBase(BaseModel):
    debut: datetime
    fin: Optional[datetime] = None
    all_day: bool = False

class OccurrenceCreate(OccurrenceBase):
    pass

class OccurrenceOut(OccurrenceBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class RatingSet(BaseModel):
    rating: conint(ge=1, le=5)
    commentaire: Optional[str] = Field(default=None, max_length=2000)

class RatingMyOut(BaseModel):
    rating: int
    commentaire: Optional[str] = None

class RatingOut(BaseModel):
    id: int
    user_id: int
    evenement_id: int
    rating: int
    commentaire: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class RatingAverage(BaseModel):
    average: float | None = None
    count: int = 0


class RatingPublicOut(BaseModel):
    id: int
    user_id: int
    user_nom: Optional[str] = None   
    rating: int
    commentaire: Optional[str] = None
    created_at: datetime



class EvenementBase(BaseModel):
    titre: str
    description: Optional[str] = ""
    longdescription: Optional[str] = ""
    prix: Optional[float] = 0.0
    image_url: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    conditions: Optional[str] = None

    keywords: Optional[List[str]] = None
    attendance_mode: Optional[int] = None
    status: Optional[int] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    accessibility: Optional[Dict[str, bool]] = None

    lieu: Optional[str] = None
    adresse: Optional[str] = None
    code_postal: Optional[str] = None
    commune: Optional[str] = None
    pays: Optional[str] = None
    pays_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class EvenementCreate(EvenementBase):
    occurrences: Optional[List[OccurrenceCreate]] = None

class EvenementResponse(EvenementBase):
    id: int
    owner_id: Optional[int] = None
    occurrences: list[OccurrenceOut] = Field(default_factory=list)
    rating_average: Optional[float] = None   # ← calculé côté service
    rating_count: int = 0                    # ← calculé côté service
    model_config = ConfigDict(from_attributes=True)


class ParticipationBase(BaseModel):
    occurrence_id: int

class ParticipationCreate(ParticipationBase):
    pass

class ParticipationOut(BaseModel):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

    occurrence_id: int
    occurrence_debut: Optional[datetime] = None
    occurrence_fin: Optional[datetime] = None
    occurrence_all_day: Optional[bool] = None

    evenement_id: int
    evenement_titre: Optional[str] = None
    evenement_commune: Optional[str] = None
    evenement_lieu: Optional[str] = None
    image_url: Optional[str] = None

    evenement_keywords: Optional[List[str]] = None

    model_config = ConfigDict(from_attributes=True)


# --- Admin DTOs ---
class AdminOverview(BaseModel):
    users_total: int
    users_new_7d: int
    organizers: int
    admins: int
    premium_active: int

    events_total: int
    events_upcoming: int
    events_past: int
    events_with_image_pct: float
    events_with_geo_pct: float

    participations_total: int
    participations_7d: int

    rating_avg_global: Optional[float] = None
    ratings_count: int

class AdminTimePoint(BaseModel):
    date: str
    count: int

class AdminTimeSeries(BaseModel):
    users: List[AdminTimePoint]
    events: List[AdminTimePoint]
    participations: List[AdminTimePoint]
    ratings: List[AdminTimePoint]

class AdminTopEventItem(BaseModel):
    id: int
    titre: str
    commune: Optional[str] = None
    image_url: Optional[str] = None
    metric: float | int

class AdminTopEvents(BaseModel):
    most_participated: List[AdminTopEventItem]
    best_rated: List[AdminTopEventItem]

class AdminContentQuality(BaseModel):
    total_events: int
    missing_image: int
    missing_geo: int
    missing_keywords: int
    missing_occurrences: int


