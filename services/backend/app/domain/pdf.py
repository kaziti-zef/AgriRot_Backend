"""T52 - Fiche A4 d'une stratégie retenue (reportlab). Échec -> 503 PDF_GENERATION_FAILED."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.errors import ApiError

MOIS = ["", "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def generer(snapshot: dict, parcelle: dict, notes: list[dict]) -> bytes:
    try:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                                topMargin=1.4 * cm, bottomMargin=1.4 * cm, title=snapshot["name"])
        st = getSampleStyleSheet()
        p = lambda t, s="BodyText": Paragraph(t, st[s])            # noqa: E731
        s = snapshot
        conf = s.get("confidence", {})
        elems = [p(f"AgroRot — {s['name']}", "Title"),
                 p(f"Parcelle <b>{parcelle['name']}</b> · {parcelle['area_ha']} ha · retenue le {s['saved_at'][:10]} "
                   f"par {s['saved_by']} · note {s['score']:.0f}/100 · résilience {s['resilience_index']:.2f} · "
                   f"confiance {conf.get('level', '?')}"), Spacer(1, 8)]
        lignes = [["Saison", "Culture", "Semis", "Récolte", "Note"]]
        for e in s["sequence"]:
            lignes.append([e["label"], e["crop_name"] + (" (suite)" if e.get("continuation") else ""),
                           MOIS[e["sowing_month"]] if e.get("sowing_month") else "—",
                           MOIS[e["harvest_month"]] if e.get("harvest_month") else "—", f"{e['season_score']:.0f}"])
        t = Table(lignes, colWidths=[3 * cm, 6 * cm, 2.5 * cm, 2.5 * cm, 2 * cm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0E3")),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        elems += [t, Spacer(1, 8)]
        ex = s["explanation"]
        for titre, cle in (("Pourquoi", "why"), ("Preuves (données NASA et saisies)", "proofs"),
                           ("Bénéfices", "benefits"), ("Risques à vérifier sur place", "local_risks_to_check"),
                           ("Informations manquantes", "information_gaps")):
            elems.append(p(titre, "Heading4"))
            elems += [p("• " + x) for x in ex.get(cle, [])]
        if s.get("off_rotation_advice"):
            elems.append(p("Conseils hors rotation", "Heading4"))
            elems += [p("• " + x) for x in s["off_rotation_advice"]]
        if notes:
            elems.append(p("Notes", "Heading4"))
            elems += [p(f"• <i>{n['author']['full_name']} ({n['kind']})</i> : {n['text']}") for n in notes]
        elems += [Spacer(1, 10), p(f"<i>{s.get('disclaimer', '')}</i>")]
        doc.build(elems)
        return buf.getvalue()
    except Exception as e:
        raise ApiError("PDF_GENERATION_FAILED", 503, "Le PDF n'a pas pu être généré. Utilisez l'impression du "
                       "navigateur.", {"reason": type(e).__name__})
