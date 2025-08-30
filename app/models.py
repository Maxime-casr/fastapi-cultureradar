
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey, UniqueConstraint,Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class Evenement(Base):
    __tablename__ = "evenements"

    id = Column(Integer, primary_key=True, index=True)
    titre = Column(String, nullable=False)
    description = Column(String)
    longdescription = Column(String)
    prix = Column(Float)
    image_url = Column(String)
    contact_email = Column(String)
    contact_phone = Column(String)
    conditions = Column(String)

    
    keywords = Column(JSONB)            
    attendance_mode = Column(Integer)   
    status = Column(Integer)            
    age_min = Column(Integer)
    age_max = Column(Integer)
    accessibility = Column(JSONB)       
    
    lieu = Column(String)
    adresse = Column(String)
    code_postal = Column(String(12))
    commune = Column(String)
    pays = Column(String(64))
    pays_code = Column(String(4))
    latitude = Column(Float)
    longitude = Column(Float)

    owner_id = Column(Integer, ForeignKey("utilisateurs.id"), nullable=True)
    owner = relationship("Utilisateur", back_populates="events")

    occurrences = relationship(
        "Occurrence",
        back_populates="evenement",
        cascade="all, delete-orphan",
        order_by="Occurrence.debut.asc()",
    )
class EventRating(Base):
    __tablename__ = "event_ratings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), index=True, nullable=False)
    evenement_id = Column(Integer, ForeignKey("evenements.id", ondelete="CASCADE"), index=True, nullable=False)
    rating = Column(Integer, nullable=False)  
    commentaire = Column(Text, nullable=True) 
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "evenement_id", name="uq_user_event_rating"),
    )
class WeatherSnapshot(Base):
    __tablename__ = "weather_snapshots"
    id = Column(Integer, primary_key=True)
    lat = Column(Float, index=True, nullable=False)
    lon = Column(Float, index=True, nullable=False)
    ts_hour = Column(DateTime, index=True, nullable=False) 
    temp_c = Column(Float)
    rain_mm = Column(Float)
    wind_kph = Column(Float)
    precip_prob = Column(Integer)   # 0..100
    is_rainy = Column(Boolean, default=False)
    is_hot   = Column(Boolean, default=False)
    is_cold  = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("lat","lon","ts_hour", name="uq_weather_loc_time"),)

class UserContext(Base):
    __tablename__ = "user_context"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    home_lat = Column(Float)
    home_lon = Column(Float)
    mobility = Column(String)  

class Occurrence(Base):
    __tablename__ = "occurrences"

    id = Column(Integer, primary_key=True)
    evenement_id = Column(Integer, ForeignKey("evenements.id", ondelete="CASCADE"), index=True, nullable=False)
    debut = Column(DateTime, nullable=False)
    fin   = Column(DateTime, nullable=True)
    all_day = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("evenement_id", "debut", "fin", name="uq_occurrence_event_time"),
    )

    evenement = relationship("Evenement", back_populates="occurrences")

class Utilisateur(Base):
    __tablename__ = "utilisateurs"

    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    mot_de_passe = Column(String, nullable=False)

    # --- nouveaux champs profil ---
    age = Column(Integer)
    preferred_slot = Column(String(16))
    available_days = Column(JSONB)
    mobility = Column(String(8))

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    role = Column(String, nullable=False, default="user")
    is_abonne = Column(Boolean, nullable=False, default=False)
    premium_since = Column(DateTime)

    events = relationship("Evenement", back_populates="owner")

class Participation(Base):
    __tablename__ = "participations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False, index=True)
    occurrence_id = Column(Integer, ForeignKey("occurrences.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="going")  
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("Utilisateur", backref="participations")
    occurrence = relationship("Occurrence", backref="participations")

    __table_args__ = (
        UniqueConstraint("user_id", "occurrence_id", name="uq_participation_user_occurrence"),
    )

class UserKeywordPref(Base):
    __tablename__ = "user_keyword_prefs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), index=True, nullable=False)
    keyword = Column(String, nullable=False, index=True)
    score = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("Utilisateur", backref="keyword_prefs")

    __table_args__ = (UniqueConstraint("user_id", "keyword", name="uq_user_keyword"),)


    
