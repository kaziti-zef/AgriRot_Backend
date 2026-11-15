"""T65 - Surveillance de la rotation choisie : la météo des 30 derniers jours et des 10 prochains jours
est-elle toujours compatible avec la culture en place ou à semer ? Sinon, notification.

Règles (simples, explicables, toutes paramétrées en tête de fichier) :
  SOWING_FAVORABLE / SOWING_DELAY  fenêtre de semis (21 j avant -> 10 j après la date prévue) :
                                   pluie des 10 derniers jours + pluie prévue à 7 jours >= 40 mm ou < 20 mm ;
  WATER_STRESS                     culture en place, sans irrigation : besoin (Kc x ET0) - 80 % de la pluie,
                                   14 jours passés + 7 jours prévus, moins une petite réserve du sol ;
  HEAVY_RAIN                       un jour prévu >= 50 mm (critique >= 80 mm) : érosion, engorgement, semis ;
  HEAT_STRESS                      >= 2 jours prévus au-dessus de l'optimum de la culture + 3 °C ;
  SEASON_ANOMALY / ROTATION_MISMATCH  pluie des 30 derniers jours < 60 % ou > 160 % de la normale : le moteur
                                   réévalue la rotation sauvegardée « si la saison continue ainsi » ; si la note
                                   baisse d'au moins 10 points, ou si la culture en cours/suivante passe sous 50,
                                   l'alerte devient critique et propose de relancer le calcul.
"""
import datetime as dt
from dataclasses import dataclass, field

FENETRE_SEMIS = (-21, 10)            # jours autour de la date de semis prévue
SEMIS_FAVORABLE_MM, SEMIS_INSUFFISANT_MM = 40, 20
STRESS_SEUILS = {"faible": (50, 90), "moyenne": (35, 70), "forte": (25, 50)}   # (avertissement, critique), mm
RESERVE_SOL_MM = 30
PLUIE_FORTE_MM, PLUIE_TRES_FORTE_MM = 50, 80
CHALEUR_MARGE_C, CHALEUR_JOURS = 3, 2
ANOMALIE_BAS, ANOMALIE_HAUT = 0.6, 1.6
BAISSE_CRITIQUE, NOTE_CRITIQUE = 10, 50
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]


def fr(x: float, d: int = 0) -> str:
    return f"{x:.{d}f}".replace(".", ",")


@dataclass
class Etape:
    index: int                     # numéro de saison dans la rotation (1..n)
    label: str
    crop_id: str
    crop_name: str
    semis: dt.date
    recolte: dt.date


@dataclass
class Alerte:
    code: str
    severity: str                  # info | warning | critical
    title: str
    message: str
    advice: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    cle: str = ""                  # clé d'anti-doublon

    def vue(self) -> dict:
        return {"code": self.code, "severity": self.severity, "title": self.title, "message": self.message,
                "advice": self.advice, "data": self.data}


# ------------------------------------------------------------------------------------------- calendrier
def calendrier(sequence: list[dict]) -> list[Etape]:
    """Séquence sauvegardée (labels « 2027-S1 », mois de semis et de récolte) -> dates. Les saisons
    « suite » d'une culture longue sont déjà couvertes par l'étape qui l'a semée."""
    out = []
    for e in sequence:
        if e.get("continuation") or e["crop_id"] == "jachere" or not e.get("sowing_month"):
            continue
        annee = int(str(e["label"])[:4])
        semis = dt.date(annee, e["sowing_month"], 15)
        recolte = dt.date(annee, e.get("harvest_month") or e["sowing_month"], 15)
        while recolte <= semis:
            recolte = recolte.replace(year=recolte.year + 1)
        out.append(Etape(e["season"], e["label"], e["crop_id"], e.get("crop_name", e["crop_id"]), semis, recolte))
    return out


def position(etapes: list[Etape], jour: dt.date) -> dict:
    en_place = next((e for e in etapes if e.semis <= jour <= e.recolte), None)
    a_semer = next((e for e in etapes if FENETRE_SEMIS[0] <= (jour - e.semis).days <= FENETRE_SEMIS[1]), None)
    suivante = next((e for e in etapes if e.semis > jour), None)
    if en_place:
        f = (jour - en_place.semis).days / max((en_place.recolte - en_place.semis).days, 1)
        phase = "in_crop"
    elif a_semer:
        phase, f = "sowing_window", None
    elif suivante:
        phase, f = ("not_started" if etapes and jour < etapes[0].semis else "between_crops"), None
    else:
        phase, f = "finished", None
    def v(e):
        return None if e is None else {"season": e.index, "label": e.label, "crop_id": e.crop_id,
                                       "crop_name": e.crop_name, "sowing_date": e.semis.isoformat(),
                                       "harvest_date": e.recolte.isoformat()}
    return {"phase": phase, "current": v(en_place), "growth_fraction": None if f is None else round(f, 2),
            "sowing": v(a_semer), "next": v(suivante),
            "_etapes": {"en_place": en_place, "a_semer": a_semer, "suivante": suivante}}


# ------------------------------------------------------------------------------------------- météo
def recaler(prev: dict, jour: dt.date) -> dict:
    """Date simulée (démo) : décale la série pour que le premier jour prévu tombe ce jour-là
    (les montants restent ceux de la vraie prévision, seules les dates changent)."""
    futurs = [d for d in prev.get("days", []) if not d.get("observe")]
    if not futurs:
        return prev
    delta = jour - dt.date.fromisoformat(futurs[0]["date"])
    jours = [{**d, "date": (dt.date.fromisoformat(d["date"]) + delta).isoformat()} for d in prev["days"]]
    return {**prev, "days": jours, "shifted_days": delta.days}


def indicateurs(prev: dict, jour: dt.date) -> dict | None:
    jours = [d for d in prev.get("days", []) if d.get("date")]
    if prev.get("status") == "unavailable" or not jours:
        return None
    # passé / futur selon la source (champ "observe") : reste juste quand on simule une autre date
    passe = lambda d: d.get("observe", dt.date.fromisoformat(d["date"]) < jour)  # noqa: E731
    passes = [d for d in jours if passe(d)]
    futurs = [d for d in jours if not passe(d)]
    p = lambda ds: sum(d["pluie_mm"] or 0 for d in ds)  # noqa: E731
    normales = (prev.get("normals") or {}).get("par_mois") or {}
    def normale(d, cle, defaut):
        n = normales.get(dt.date.fromisoformat(d["date"]).month) or normales.get(str(dt.date.fromisoformat(d["date"]).month))
        return (n or {}).get(cle, defaut)
    p30 = passes[-30:]
    normale30 = sum(normale(d, "pluie_mm_j", 0) for d in p30) if normales else None
    tmax_obs = [d["t_max"] for d in p30 if d["t_max"] is not None]
    tmax_norm = [normale(d, "t_max_c", None) for d in p30 if d["t_max"] is not None]
    anomalie_t = (sum(tmax_obs) / len(tmax_obs) - sum(tmax_norm) / len(tmax_norm)) \
        if tmax_obs and normales and None not in tmax_norm else None
    forte = max(futurs, key=lambda d: d["pluie_mm"] or 0, default=None)
    return {
        "rain_last_30d_mm": round(p(p30), 1), "rain_normal_30d_mm": None if normale30 is None else round(normale30, 1),
        "rain_ratio_30d": None if not normale30 else round(p(p30) / normale30, 2),
        "rain_last_10d_mm": round(p(passes[-10:]), 1), "rain_next_7d_mm": round(p(futurs[:7]), 1),
        "max_daily_rain_mm": None if forte is None else forte["pluie_mm"], "max_daily_rain_date": None if forte is None else forte["date"],
        "tmax_anomaly_30d_c": None if anomalie_t is None else round(anomalie_t, 1),
        "_passes": passes, "_futurs": futurs, "_normale": normale,
    }


def _kc(c: dict, f: float) -> float:
    k0, k1, k2 = (c.get("kc") or [0.5, 1.0, 0.8])
    if f < 0.15:
        return k0
    if f < 0.4:
        return k0 + (k1 - k0) * (f - 0.15) / 0.25
    if f < 0.8:
        return k1
    return k1 + (k2 - k1) * (f - 0.8) / 0.2


# ------------------------------------------------------------------------------------------- règles
def regles(pos: dict, ind: dict, cultures: dict[str, dict], irrigue: bool, pente: float | None,
           saved_id: str, jour: dt.date) -> list[Alerte]:
    out: list[Alerte] = []
    semaine = jour.isocalendar()
    sem = f"{semaine[0]}W{semaine[1]:02d}"
    en_place, a_semer = pos["_etapes"]["en_place"], pos["_etapes"]["a_semer"]

    # --- semis
    if a_semer is not None:
        c = a_semer
        cumul = ind["rain_last_10d_mm"] + ind["rain_next_7d_mm"]
        d = {"crop_id": c.crop_id, "season": c.index, "sowing_date": c.semis.isoformat(), "rain_mm": round(cumul, 1)}
        if cumul >= SEMIS_FAVORABLE_MM:
            out.append(Alerte("SOWING_FAVORABLE", "info", f"Bonnes conditions pour semer : {c.crop_name}",
                              f"{fr(cumul)} mm de pluie (10 derniers jours et 7 prochains jours) : le sol devrait être "
                              f"assez humide pour semer {c.crop_name.lower()} ({c.label}).",
                              ["Semer après une pluie d'au moins 20 mm.", "Prévoir les semences et la main-d'œuvre."],
                              d, f"{saved_id}:SOWING_FAVORABLE:{c.index}"))
        elif cumul < SEMIS_INSUFFISANT_MM:
            out.append(Alerte("SOWING_DELAY", "warning", f"Retarder le semis : {c.crop_name}",
                              f"Seulement {fr(cumul)} mm de pluie (10 derniers jours et 7 prochains jours). Un semis "
                              f"maintenant risque de mal lever : attendre une pluie utile.",
                              ["Attendre une pluie d'au moins 20 mm avant de semer.",
                               "Si l'attente dépasse 3 semaines, relancer le calcul de la rotation."],
                              d, f"{saved_id}:SOWING_DELAY:{c.index}:{sem}"))

    # --- culture en place
    if en_place is not None:
        c, info = en_place, cultures.get(en_place.crop_id, {})
        f = pos["growth_fraction"] or 0
        if not irrigue:
            fen = ind["_passes"][-14:] + ind["_futurs"][:7]
            kc = _kc(info, f)
            besoin = sum(kc * (d["et0_mm"] if d["et0_mm"] is not None else ind["_normale"](d, "et0_mm_j", 3.8)) for d in fen)
            apport = sum(0.8 * (d["pluie_mm"] or 0) for d in fen)
            deficit = besoin - apport - RESERVE_SOL_MM
            avert, crit = STRESS_SEUILS.get(info.get("drought_sensitivity") or "moyenne", STRESS_SEUILS["moyenne"])
            if deficit >= avert:
                grav = "critical" if deficit >= crit else "warning"
                out.append(Alerte("WATER_STRESS", grav, f"Manque d'eau probable : {c.crop_name}",
                                  f"Sur 3 semaines (14 jours passés et 7 à venir), la culture aura besoin d'environ "
                                  f"{fr(besoin)} mm d'eau et la pluie n'en apportera qu'environ {fr(apport)} mm.",
                                  ["Pailler le sol pour limiter l'évaporation.", "Désherber : les adventices consomment l'eau.",
                                   "Irrigation d'appoint si une source d'eau est disponible."],
                                  {"crop_id": c.crop_id, "deficit_mm": round(deficit), "need_mm": round(besoin),
                                   "rain_mm": round(apport)}, f"{saved_id}:WATER_STRESS:{c.index}:{grav}:{sem}"))
        t_opt = info.get("t_opt_max_c")
        seuil = (t_opt + CHALEUR_MARGE_C) if t_opt is not None else 35
        chauds = [d for d in ind["_futurs"] if d["t_max"] is not None and d["t_max"] >= seuil]
        if len(chauds) >= CHALEUR_JOURS:
            out.append(Alerte("HEAT_STRESS", "warning", f"Fortes chaleurs prévues : {c.crop_name}",
                              f"{len(chauds)} jours au-dessus de {fr(seuil)} °C dans les 10 prochains jours "
                              f"(maximum {fr(max(d['t_max'] for d in chauds), 1)} °C). La floraison est la phase la plus sensible.",
                              ["Éviter les traitements et les travaux aux heures chaudes.", "Garder le sol couvert (paillage)."],
                              {"crop_id": c.crop_id, "days": [d["date"] for d in chauds], "threshold_c": seuil},
                              f"{saved_id}:HEAT_STRESS:{c.index}:{chauds[0]['date']}"))

    # --- pluie forte (culture en place ou semis récent/prochain)
    cible = en_place or a_semer
    if cible is not None and ind["max_daily_rain_mm"] and ind["max_daily_rain_mm"] >= PLUIE_FORTE_MM:
        mm, date = ind["max_daily_rain_mm"], ind["max_daily_rain_date"]
        info = cultures.get(cible.crop_id, {})
        conseils = ["Curer les rigoles et les fossés de drainage avant la pluie."]
        if pente and pente > 5:
            conseils.append(f"Pente de {fr(pente)}° : renforcer les billons en courbes de niveau, garder les résidus au sol.")
        if not info.get("waterlogging_tolerant"):
            conseils.append(f"{cible.crop_name} supporte mal l'eau stagnante : vérifier l'écoulement des zones basses.")
        if a_semer is not None and en_place is None:
            conseils.append("Ne pas semer juste avant cette pluie : les semences risquent d'être emportées.")
        out.append(Alerte("HEAVY_RAIN", "critical" if mm >= PLUIE_TRES_FORTE_MM else "warning",
                          f"Forte pluie prévue le {dt.date.fromisoformat(date).day} {MOIS[dt.date.fromisoformat(date).month - 1]}",
                          f"Environ {fr(mm)} mm attendus en un jour : risque d'érosion et d'engorgement.", conseils,
                          {"crop_id": cible.crop_id, "rain_mm": mm, "date": date}, f"{saved_id}:HEAVY_RAIN:{date}"))
    return out


def scenario_observe(ind: dict) -> dict | None:
    """Anomalie des 30 derniers jours -> scénario du moteur (bornes du contrat)."""
    r = ind.get("rain_ratio_30d")
    if r is None or ANOMALIE_BAS <= r <= ANOMALIE_HAUT:
        return None
    pluie = int(max(-30, min(30, round((r - 1) * 100))))
    t = ind.get("tmax_anomaly_30d_c") or 0
    return {"rain_delta_pct": pluie, "temp_delta_c": round(max(0.0, min(3.0, t)), 1), "horizon_years": 0}
