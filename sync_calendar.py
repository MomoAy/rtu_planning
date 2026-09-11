"""
Génère un fichier .ics à jour à partir du planning de groupe publié sur
nodarbibas.rtu.lv, en ne gardant que les matières réellement suivies.

Usage :
    python sync_calendar.py

Le script ne demande rien de manière interactive : toute la config est en
haut de ce fichier. C'est ce qui permet de le lancer automatiquement via
GitHub Actions (voir .github/workflows/update-calendar.yml).
"""

import hashlib
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

BASE_URL = "https://nodarbibas.rtu.lv"

# La date brute renvoyée par l'API (eventDate) représente minuit heure de
# Riga. Il faut l'interpréter explicitement dans ce fuseau, sinon le résultat
# dépend du fuseau de la machine qui exécute le script (ex: UTC sur GitHub
# Actions) et les cours peuvent se décaler d'un jour.
RIGA_TZ = ZoneInfo("Europe/Riga")

# ---------------------------------------------------------------------------
# CONFIG — à adapter si besoin (nouveau semestre, changement de groupe, etc.)
# ---------------------------------------------------------------------------

# Sous-chaîne qui identifie ton semestre dans la liste déroulante du site
# (ex: "26/27-A" pour "2026/2027 Autumn semester (26/27-A)")
SEMESTER_LABEL_CONTAINS = "26/27-A"

# Code de ton programme d'études (visible entre parenthèses sur le site)
PROGRAM_CODE = "ADMD0"  # Computer Systems

# Année d'étude et numéro de groupe, tels qu'affichés sur nodarbibas.rtu.lv
COURSE_ID = "1"
GROUP_ID = "800"

# Matières réellement suivies. Matching insensible à la casse : un événement
# est gardé si une de ces chaînes apparaît dans son intitulé. Si une matière
# manque à l'arrivée, regarde les logs du run GitHub Actions (section
# "Matières ignorées") pour ajuster le mot-clé ici.
MY_COURSES = [
    "Advanced data technologies",
    "Basics of Logistics and Supply Chain Management",
    "Enterprise Information Technology Architecture",
    "Information Retrieval",
    "Model-Based Systems Engineering",
]

OUTPUT_FILE = "planning.ics"

# ---------------------------------------------------------------------------


# Une seule session HTTP réutilisée partout : le site retient la langue
# choisie au premier chargement de page au niveau de la session (cookie
# JSESSIONID). Sans ça, chaque appel repart sur la langue par défaut (letton).
SESSION = requests.Session()


def api_post(path: str, data: dict) -> dict | list:
    # "lang": "en" est aussi envoyé sur chaque appel, au cas où le serveur en
    # tienne compte en plus (ou à la place) du cookie de session.
    payload = {"lang": "en", **data}
    resp = SESSION.post(f"{BASE_URL}/{path}", data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_semester_id() -> tuple[str, str]:
    resp = SESSION.get(BASE_URL + "/", params={"lang": "en"}, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    options = soup.select("#semester-id option")

    for opt in options:
        if SEMESTER_LABEL_CONTAINS in opt.text:
            return str(opt["value"]), opt.text.strip()

    available = [o.text.strip() for o in options]
    raise SystemExit(
        f"Semestre contenant '{SEMESTER_LABEL_CONTAINS}' introuvable.\n"
        f"Options disponibles sur le site : {available}"
    )


def get_semester_dates(ctx: dict) -> tuple[datetime, datetime]:
    json = api_post("getChousenSemesterStartEndDate", ctx)
    start = datetime.fromtimestamp(json["startDate"] // 1000, tz=RIGA_TZ)
    end = datetime.fromtimestamp(json["endDate"] // 1000, tz=RIGA_TZ)
    return start, end


def get_program_id(ctx: dict) -> str:
    departments = api_post("findProgramsBySemesterId", ctx)
    for dept in departments:
        for program in dept.get("program", []):
            if program.get("code") == PROGRAM_CODE:
                return program["programId"]

    available = sorted(
        {p.get("code") for d in departments for p in d.get("program", [])}
    )
    raise SystemExit(
        f"Programme '{PROGRAM_CODE}' introuvable pour ce semestre.\n"
        f"Codes disponibles : {available}"
    )


def get_semester_program_id(ctx: dict) -> str:
    groups = api_post("findGroupByCourseId", ctx)
    for group in groups:
        if str(group.get("group")) == str(GROUP_ID):
            return group["semesterProgramId"]

    available = sorted({str(g.get("group")) for g in groups})
    raise SystemExit(
        f"Groupe '{GROUP_ID}' introuvable pour ce cours/programme.\n"
        f"Groupes disponibles : {available}"
    )


def is_published(ctx: dict) -> bool:
    return bool(api_post("isSemesterProgramPublished", ctx))


def get_all_raw_events(ctx: dict, start: datetime, end: datetime) -> list:
    events = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)

    while cursor <= last:
        payload = {**ctx, "year": cursor.year, "month": cursor.month}
        try:
            month_events = api_post("getSemesterProgEventList", payload)
        except requests.RequestException:
            month_events = []
        events.extend(month_events)
        cursor = cursor + relativedelta(months=1)

    return events


def parse_event(raw: dict) -> dict:
    event_date = datetime.fromtimestamp(raw["eventDate"] // 1000, tz=RIGA_TZ)
    start_t = raw["customStart"]
    end_t = raw["customEnd"]
    return {
        "subject": (raw.get("eventTempNameEn") or raw.get("eventTempName") or "").strip(),
        "location": (raw.get("roomInfoTextEn") or raw.get("roomInfoText") or "").strip(),
        "start": event_date.replace(hour=start_t["hour"], minute=start_t["minute"], tzinfo=None),
        "end": event_date.replace(hour=end_t["hour"], minute=end_t["minute"], tzinfo=None),
    }


def keep_event(subject: str) -> bool:
    subject_lower = subject.lower()
    return any(course.lower() in subject_lower for course in MY_COURSES)


def stable_uid(event: dict) -> str:
    """
    UID déterministe basé sur le contenu de l'événement (pas un UUID aléatoire).
    Indispensable pour qu'un abonnement iOS/Google Calendar reconnaisse "le
    même" événement d'un jour à l'autre au lieu de créer un doublon à chaque
    régénération du fichier.
    """
    key = f"{event['subject']}|{event['start'].isoformat()}|{event['end'].isoformat()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"{digest}@rtu-calendar-sync"


VTIMEZONE = "\n".join(
    [
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Riga",
        "X-LIC-LOCATION:Europe/Riga",
        "BEGIN:DAYLIGHT",
        "TZNAME:EEST",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0300",
        "DTSTART:19700329T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZNAME:EET",
        "TZOFFSETFROM:+0300",
        "TZOFFSETTO:+0200",
        "DTSTART:19701025T040000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
)


def write_ics(events: list[dict]) -> None:
    fmt = "%Y%m%dT%H%M00"
    now_stamp = datetime.now(timezone.utc).strftime(fmt) + "Z"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//mhd//rtu-calendar-sync//EN",
        "CALSCALE:GREGORIAN",
        VTIMEZONE,
    ]

    for event in sorted(events, key=lambda e: e["start"]):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{stable_uid(event)}",
            f"DTSTAMP:{now_stamp}",
            f"DTSTART;TZID=Europe/Riga:{event['start'].strftime(fmt)}",
            f"DTEND;TZID=Europe/Riga:{event['end'].strftime(fmt)}",
            f"SUMMARY:{event['subject']}",
            f"LOCATION:{event['location']}",
            "SEQUENCE:0",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    ctx: dict = {}

    ctx["semesterId"], semester_label = get_semester_id()
    print(f"Semestre : {semester_label} (id={ctx['semesterId']})")

    start, end = get_semester_dates(ctx)
    print(f"Période : {start.date()} -> {end.date()}")

    ctx["programId"] = get_program_id(ctx)
    ctx["courseId"] = COURSE_ID
    ctx["semesterProgramId"] = get_semester_program_id(ctx)

    if not is_published(ctx):
        print("Le planning n'est pas encore publié pour ce groupe. Rien à faire.")
        sys.exit(0)

    raw_events = get_all_raw_events(ctx, start, end)

    if "--dump-raw" in sys.argv:
        import json

        print(json.dumps(raw_events[0], indent=2, ensure_ascii=False))
        return

    events = [parse_event(r) for r in raw_events]

    kept = [e for e in events if keep_event(e["subject"])]
    ignored_subjects = sorted({e["subject"] for e in events if not keep_event(e["subject"])})

    print(f"{len(events)} événements trouvés pour le groupe, {len(kept)} gardés après filtre.")
    if ignored_subjects:
        print("Matières ignorées (absentes de MY_COURSES) :")
        for subject in ignored_subjects:
            print(f"  - {subject}")

    write_ics(kept)
    print(f"Écrit dans {OUTPUT_FILE} ({len(kept)} événements).")


if __name__ == "__main__":
    main()