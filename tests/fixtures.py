"""Response fixtures.

They are constructed from the documented response schemas (bundesAPI OpenAPI specs for
Jobsuche/Entgeltatlas, the ESCO HAL format, O*NET file layouts) and from the field names used by
other clients that are tested against the live BA APIs.  They are *not* captured live responses.
"""

from __future__ import annotations

JOBSUCHE_V6 = {
    "maxErgebnisse": "2",
    "page": "1",
    "size": "25",
    "woOutput": {"bereinigterOrt": "Berlin"},
    "ergebnisliste": [
        {
            "referenznummer": "10000-1184867112-S",
            "stellenangebotsTitel": "Buchhalter (m/w/d)",
            "firma": "Muster GmbH",
            "hauptberuf": "Buchhalter/in",
            "stellenlokationen": [{"adresse": {"plz": "10115", "ort": "Berlin", "land": "Deutschland"}}],
            "entfernung": 3,
            "stellenangebotsart": "ARBEIT",
            "arbeitszeitVollzeit": True,
            "veroeffentlichungszeitraum": {"von": "2026-10-20"},
            "eintrittszeitraum": {"von": "2026-11-01"},
        },
        {
            "referenznummer": "10001-1002716922-S",
            "stellenangebotsTitel": "Finanzbuchhalter",
            "firma": "Beispiel AG",
            "hauptberuf": "Finanzbuchhalter/in",
            "stellenlokationen": [{"adresse": {"plz": "10178", "ort": "Berlin"}}],
            "veroeffentlichungszeitraum": {"von": "2026-10-22"},
        },
    ],
}

JOBSUCHE_V4 = {
    "maxErgebnisse": "1",
    "page": "1",
    "size": "50",
    "stellenangebote": [
        {
            "hashId": "WBTAiM10b25rJgZqiLhVIHzAF9e0rnV_DXdsRZtlb54=",
            "beruf": "Elektroinstallateur/in",
            "titel": "Elektriker (m/w/d)",
            "refnr": "10000-1184867113-S",
            "arbeitgeber": "Gröger & Oltermann GmbH",
            "aktuelleVeroeffentlichungsdatum": "2026-07-25",
            "eintrittsdatum": "2026-07-26",
            "arbeitsort": {
                "plz": 90537,
                "ort": "Feucht",
                "region": "Bayern",
                "land": "Deutschland",
                "koordinaten": {"lat": 49.37, "lon": 11.21},
            },
            "modifikationsTimestamp": "2026-07-25T13:12:33.913",
        }
    ],
}

JOBDETAIL_V4_OLD = {
    "refnr": "10000-1184867113-S",
    "titel": "Elektriker (m/w/d)",
    "stellenangebotsBeschreibung": "<p>Ihre Aufgaben:</p><ul><li>Installation</li><li>Wartung</li></ul>",
    "arbeitgeber": "Gröger & Oltermann GmbH",
    "branche": "Elektroinstallation",
    "branchengruppe": "Handwerk",
    "beruf": "Elektroinstallateur/in",
    "hauptDkz": "9907",
    "arbeitsorte": [{"ort": "Feucht", "plz": "90537", "region": "Bayern", "land": "Deutschland"}],
    "fertigkeiten": [
        {"hierarchieName": "Elektrotechnik", "auspraegungen": {"Erweiterte Kenntnisse": ["Elektroinstallation"]}},
        {"hierarchieName": "Sonstiges", "auspraegungen": {"Grundkenntnisse": ["Wartung", "Elektroinstallation"]}},
    ],
    "verguetung": "Tarif",
    "modifikationsTimestamp": "2026-07-25T13:12:33.913",
}

JOBDETAIL_NEW = {
    "referenznummer": "10000-1184867112-S",
    "stellenangebotsTitel": "Buchhalter (m/w/d)",
    "firma": "Muster GmbH",
    "hauptberuf": "Buchhalter/in",
    "stellenangebotsBeschreibung": "Wir suchen Unterstützung in der Buchhaltung.",
    "verguetungsangabe": "KEINE_ANGABEN",
    "vertragsdauer": "UNBEFRISTET",
    "datumErsteVeroeffentlichung": "2026-10-20",
    "aenderungsdatum": "2026-10-21T08:00:00",
    "stellenlokationen": [{"adresse": {"plz": "10115", "ort": "Berlin"}}],
    "allianzpartnerName": "arbeitsagentur.de",
    "istZeitarbeit": False,
}

BERUFENET_LIST = {
    "_embedded": {
        "berufSucheList": [
            {"id": 58779, "kurzBezeichnungNeutral": "Buchhalter/in"},
            {"id": 9069, "kurzBezeichnungNeutral": "Finanzbuchhalter/in"},
        ]
    },
    "page": {"size": 20, "totalElements": 2, "totalPages": 1, "number": 0},
}

BERUFENET_DETAIL = [
    {
        "id": 58779,
        "kurzBezeichnungNeutral": "Buchhalter/in",
        "bezeichnungNeutral": "Buchhalter/in",
        "kldb2010": "B 72213",
        "infofelder": [
            {"id": "b02", "ueberschrift": "Bilder", "content": "<img src='x.png'>"},
            {
                "id": "b10-0",
                "ueberschrift": "Aufgaben und Tätigkeiten kompakt",
                "content": "<p>Buchhalter/innen erfassen Geschäftsvorfälle.</p><ul><li>Belege kontieren und buchen</li>"
                "<li>Konten abstimmen</li><li>Monatsabschlüsse vorbereiten</li></ul>",
            },
            {
                "id": "b11-0",
                "ueberschrift": "Aufgaben und Tätigkeiten ausführlich",
                "content": "<h3>Laufende Buchhaltung</h3><p>Sie prüfen Rechnungen und überwachen Zahlungseingänge.</p>",
            },
            {"id": "b30-0", "ueberschrift": "Zugang", "content": "<p>Weiterbildung</p>"},
        ],
        "taetigkeitsfelder": [{"kurzBezeichnungNeutral": "Rechnungswesen"}, {"kurzBezeichnungNeutral": "Controlling"}],
    }
]

ENTGELTE = [
    {
        "kldb": "72213",
        "region": {"id": 1, "bezeichnung": "Deutschland", "schluessel": "D", "beitragsBemessungsGrenze": 8050},
        "gender": {"id": 1, "bezeichnung": "Gesamt"},
        "ageCategory": {"id": 1, "bezeichnung": "Gesamt"},
        "performanceLevel": {"id": 2, "bezeichnung": "Fachkraft"},
        "branche": {"id": 1, "bezeichnung": "Gesamt"},
        "entgelt": 3954,
        "entgeltQ25": 3312,
        "entgeltQ75": 4689,
        "besetzung": 254321,
    },
    {
        "kldb": "72213",
        "region": {"id": 1, "bezeichnung": "Deutschland"},
        "gender": {"id": 1, "bezeichnung": "Gesamt"},
        "ageCategory": {"id": 1, "bezeichnung": "Gesamt"},
        "performanceLevel": {"id": 2, "bezeichnung": "Fachkraft"},
        "branche": {"id": 4, "bezeichnung": "Baugewerbe"},
        "entgelt": -1,
        "besetzung": 0,
    },
]

ESCO_OCC_URI = "http://data.europa.eu/esco/occupation/aaa-buchhalter"
ESCO_SKILL_1 = "http://data.europa.eu/esco/skill/s1"
ESCO_SKILL_2 = "http://data.europa.eu/esco/skill/s2"

ESCO_SEARCH = {
    "total": 1,
    "_embedded": {
        "results": [
            {
                "uri": ESCO_OCC_URI,
                "title": "Buchhalter/Buchhalterin",
                "className": "Occupation",
                "preferredLabel": {"de": "Buchhalter/Buchhalterin", "en": "accountant"},
            }
        ]
    },
}

ESCO_OCCUPATION = {
    "uri": ESCO_OCC_URI,
    "className": "Occupation",
    "code": "2411.1",
    "preferredLabel": {"de": "Buchhalter/Buchhalterin", "en": "accountant"},
    "alternativeLabel": {"de": ["Bilanzbuchhalter", "Finanzbuchhalterin"]},
    "description": {"de": {"literal": "Buchhalter analysieren Finanzunterlagen.", "mimetype": "plain/text"}},
    "_links": {
        "self": {"href": "https://ec.europa.eu/esco/api/resource/occupation?uri=x", "uri": ESCO_OCC_URI},
        "hasEssentialSkill": [
            {"href": "h1", "uri": ESCO_SKILL_1, "title": "Buchführungsvorschriften anwenden"},
            {"href": "h2", "uri": ESCO_SKILL_2, "title": "Finanzberichte erstellen"},
        ],
        "hasOptionalSkill": {"href": "h3", "uri": "http://data.europa.eu/esco/skill/s3", "title": "Steuerrecht"},
        "broaderIscoGroup": [{"href": "h4", "uri": "http://data.europa.eu/esco/isco/C2411", "title": "Accountants"}],
    },
}

ESCO_ISCO_GROUP = {
    "uri": "http://data.europa.eu/esco/isco/C2411",
    "code": "2411",
    "preferredLabel": {"de": "Wirtschaftsprüfer und Buchhalter"},
    "_links": {
        "narrowerOccupation": [
            {"uri": ESCO_OCC_URI, "title": "Buchhalter/Buchhalterin"},
            {"uri": "http://data.europa.eu/esco/occupation/bbb-pruefer", "title": "Wirtschaftsprüfer"},
        ]
    },
}

ONET_OCCUPATIONS = (
    "O*NET-SOC Code\tTitle\tDescription\n"
    "13-2011.00\tAccountants and Auditors\tExamine, analyze, and interpret accounting records.\n"
    "15-1252.00\tSoftware Developers\tResearch, design, and develop computer software.\n"
)

ONET_TASKS = (
    "O*NET-SOC Code\tTask ID\tTask\tTask Type\tIncumbents Responding\tDate\tDomain Source\n"
    "13-2011.00\t1\tPrepare detailed reports on audit findings.\tCore\t110\t07/2023\tIncumbent\n"
    "13-2011.00\t2\tReport to management about asset utilization and audit results.\tCore\t110\t07/2023\tIncumbent\n"
    "13-2011.00\t3\tReview accounts for discrepancies and reconcile differences.\tSupplemental\t110\t07/2023\t"
    "Incumbent\n"
    "15-1252.00\t16363\tModify existing software to correct errors.\tCore\t25\t08/2024\tIncumbent\n"
)

HN_SEARCH = {
    "hits": [
        {
            "objectID": "4242",
            "_tags": ["comment", "author_jdoe"],
            "author": "jdoe",
            "comment_text": "We <i>automated</i> our invoice processing with an LLM pipeline.",
            "story_title": "Ask HN: What did you automate this year?",
            "created_at": "2026-09-01T10:00:00Z",
            "points": None,
            "story_id": 4200,
        },
        {
            "objectID": "4300",
            "_tags": ["story"],
            "title": "Automating bookkeeping reconciliation",
            "url": "https://example.com/post",
            "author": "acme",
            "created_at": "2026-09-02T10:00:00Z",
            "points": 120,
            "num_comments": 40,
        },
    ],
    "nbHits": 2,
}

ARBEITNOW_PAGE = {
    "data": [
        {
            "slug": "python-developer-berlin-123",
            "company_name": "Startup GmbH",
            "title": "Python Developer",
            "description": "<p>Build APIs with Python.</p>",
            "remote": True,
            "url": "https://www.arbeitnow.com/jobs/companies/startup/python-developer-berlin-123",
            "tags": ["Software Development"],
            "job_types": ["full time"],
            "location": "Berlin",
            "created_at": 1761700000,
        },
        {
            "slug": "koch-muenchen-9",
            "company_name": "Restaurant KG",
            "title": "Koch (m/w/d)",
            "description": "Kochen.",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/companies/restaurant/koch-muenchen-9",
            "tags": [],
            "job_types": [],
            "location": "München",
            "created_at": 1761600000,
        },
    ],
    "links": {"next": None},
    "meta": {"current_page": 1},
}
