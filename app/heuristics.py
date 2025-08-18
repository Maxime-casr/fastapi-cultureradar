# app/reco/heuristics.py
import re, unicodedata
OUTDOOR_CUES = {"plein air","parc","jardin","festival","street","parcours","balade","marche","open air","quai","berge","foret","randonnée","pique-nique"}
INDOOR_CUES  = {"musée","cinéma","theatre","salle","auditorium","galerie","bibliotheque","maison","centre","indoor"}

def _norm(s:str|None)->str:
    if not s: return ""
    t = unicodedata.normalize('NFD', s.lower())
    return "".join(c for c in t if unicodedata.category(c)!='Mn')

def guess_outdoor(e) -> int:
    text = " ".join([
        _norm(e.titre), _norm(e.description),
        _norm(e.lieu), _norm(e.adresse),
        " ".join((_norm(k) for k in (e.keywords or [])))
    ])
    score = 0
    score += sum(1 for w in OUTDOOR_CUES if w in text)
    score -= sum(1 for w in INDOOR_CUES if w in text)
    # attendance_mode: 1 offline, 2 online, 3 mixed → online/mixed ≈ pas outdoor
    if (e.attendance_mode or 0) in (2,3): score -= 2
    return score  # >0 = outdoor likely, <0 = indoor likely
