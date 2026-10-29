# Faktencheck: Recherche „Job-Graph für Deutschland per MCP“

Stand: 29.10.2026. Geprüft wurden zwei Recherchetexte: der Haupttext zu MCP-Servern, Datenquellen und Graph-Modell und der Nachtrag „weitere Quellen“ mit ATS-APIs und Adzuna. Am Ende steht die Prüfung des Prototyps `berufsgraph-mcp`.

**Kennzeichnung der Belege**

- **[P]** Primärquelle direkt gelesen: OpenAPI-Spezifikationen und READMEs auf GitHub (raw), PyPI-/npm-Metadaten, Quellcode des installierten MCP-SDK 2.3.0, Quellcode anderer Clients.
- **[S]** nur über Suchmaschinen-Ausschnitte geprüft, weil die Seite aus der Prüfumgebung nicht erreichbar war.
- **[N]** nicht verifizierbar.

**Grenzen der Prüfung:** Die Netzwerk-Policy der Prüfumgebung blockierte die Daten-Hosts. Betroffen waren `rest.arbeitsagentur.de`, `ec.europa.eu`, `onetcenter.org`, `arbeitnow.com`, `hn.algolia.com`, `statistik.arbeitsagentur.de`, `commoncrawl.org`, die ATS-Hosts und `adzuna.com`. Live-Antworten der APIs konnten deshalb **nicht** geprüft werden. Zahlen, die sich täglich ändern (offene Stellen), sind daher nicht bestätigt. Das MCP-Tool `check_sources` holt die Prüfung der Erreichbarkeit auf dem eigenen Rechner nach.

---

## Die wichtigsten Korrekturen

1. **Die BA-Jobsuche ist keine „offizielle, ToS-konforme“ API.** Dokumentiert wird sie vom Community-Projekt bundesAPI. Dessen README sagt wörtlich, die BA biete „bis heute keine offizielle API an“ [P]. Für BERUFENET und den Entgeltatlas gilt dasselbe [P]. Die Endpunkte können sich jederzeit ändern. Veröffentlichte Nutzungsbedingungen für diese Schnittstellen gibt es nicht.
2. **Das MCP-SDK heißt nicht mehr FastMCP.** Seit `mcp` 2.0.0 (28.07.2026) heißt die Klasse `MCPServer`. `from mcp.server.fastmcp import FastMCP` endet in `ModuleNotFoundError` [P, im installierten SDK 2.3.0 nachgesehen]. Der Transport SSE ist veraltet; der Standard ist stdio bzw. Streamable HTTP [P].
3. **Die Jobsuche v6 hat ein neues Antwortformat.** Die OpenAPI-Spezifikation nennt `/pc/v6/jobs` richtig, beschreibt aber noch das alte Format `stellenangebote`/`arbeitsort`. Clients, die gegen die Live-API testen, lesen `ergebnisliste`/`stellenlokationen` [P, Code von slopinger/arbeitsagentur-mcp]. WorkMCP unterstützt beide Formate.
4. **BERUFENET hat eine JSON-Schnittstelle.** Sie liegt unter `rest.arbeitsagentur.de/infosysbub/bnet/pc/v1/berufe` (X-API-Key `infosysbub-berufenet`), inoffiziell und von bundesAPI dokumentiert [P]. Scraping ist nicht nötig.
5. **Gehaltsbänder gibt es amtlich.** Der Entgeltatlas der BA liefert Median und Quartile nach KldB-Code, Region, Anforderungsniveau, Geschlecht, Alter und Branche als JSON [P]. Die Aussage „Adzuna ist die einzige programmatische Gehaltsquelle“ ist falsch. Adzuna liefert *inserierte* und teils *geschätzte* Gehälter [P].
6. **KldB-Codes verbinden Berufe nicht mit Wirtschaftszweigen.** Die KldB 2010 ist eine Berufsklassifikation. Branchen werden mit der WZ (WZ 2008, Umstellung auf WZ 2025) klassifiziert; eine Verknüpfung entsteht nur über Statistiken wie „Beschäftigte nach Beruf × Wirtschaftszweig“. Primärquelle der KldB ist die BA-Statistik (Fassung 2020, Umsteigeschlüssel zu ISCO-08), nicht ein BIBB-PDF [S].
7. **„Kein fertiger MCP-Server für BERUFENET/ESCO/KldB“ ist zu absolut.** *Etabliert* ist keiner, unreife Server gibt es aber, u. a. für BERUFENET, ESCO und O*NET (siehe Abschnitt 2) [P/S].
8. **Die Quellenangaben sind verschoben.** In der ersten Tabelle gehört jede Fußnote zur Nachbarzeile, alle zehn geprüften Fälle sind betroffen [P/S]. Der Nachtrag hat dasselbe Muster.
9. **Zur O*NET-Lizenz fehlt etwas.** O*NET steht unter CC BY 4.0 und verlangt Namensnennung. Der verlinkte Datenwörterbuch-Eintrag gehört zu Release 20.1 von 2015; aktuell ist Release 31.0 (August 2026) [S].
10. **Cobrainer-Zahlen sind nicht öffentlich belegt.** „~250.000 Skills“ und „15 Jahre“ lassen sich nicht bestätigen. Öffentlich genannt werden „170.000+ Skills“ und die Gründung 2013 [S].

---

## 1. Fertige MCP-Server (Tabelle im Haupttext)

| Aussage | Urteil | Befund |
|---|---|---|
| **wunderfrucht/jobsuche-mcp-server** deckt die BA-Jobsuche ab, `search_jobs` mit Filtern, „offizielle, ToS-konforme REST-API“ | teilweise korrekt | Das Repo gibt es: Rust, MIT, 5 Tools (`search_jobs`, `get_job_details`, `search_jobs_with_details`, `batch_search_jobs`, `get_server_status`). Letzter Commit am 23.10.2025. Das npm-Paket, das die README empfiehlt, liefert 404 [P]. Die API ist **nicht** offiziell (Korrektur 1). Als „Fundament“ eher ungeeignet: seit einem Jahr inaktiv. |
| **mcp-jobspy** (PyPI, v1.4.1): LinkedIn, Indeed, Glassdoor, ZipRecruiter, Bayt, Naukri; `search_jobs`, `get_job_details`, Export CSV/JSON/JSONL | korrekt | Version 1.4.1 vom 23.10.2026 ist aktuell. Das Paket gehört zu speedyapply/JobSpy und unterstützt zusätzlich BDJobs und HelloWork [P]. StepStone, XING und die BA sind nicht dabei. |
| **kdkiss/mcp-stepstone**: strukturiertes JSON, Deduplizierung, Ort-/Umkreisfilter | teilweise korrekt | Der Server liefert **Fließtext**, kein JSON. Dedupliziert wird nur innerhalb eines Suchbegriffs, abgerufen wird nur die erste Ergebnisseite [P]. |
| **0xCybin/jobs-mcp**: RemoteOK, HN „Who is Hiring“, Arbeitnow, GitHub Issues, Upwork; `job_scan`, `search_arbeitnow_jobs` | korrekt | Hobbyprojekt: TypeScript, 1 Stern, 2 Commits vom Februar 2026 [P]. |
| **Apify Arbeitsagentur Jobs Scraper** als gehosteter MCP-Endpoint | weitgehend korrekt | Kostenpflichtig (ab ca. 0,96 $ je 1.000 Ergebnisse) und nur über ein Apify-Konto mit OAuth nutzbar [S]. Der Actor ist eine Hülle um dieselbe frei abrufbare API. **Nicht integriert**, weil keine Bezahl-APIs genutzt werden sollen. |
| **WorkAist**: Recruiting-MCP mit BA-Integration, 6 Tools inkl. `list_jobs` | nicht verifizierbar | Die Seite war nicht erreichbar. Laut Snippets folgen alle Connector-Seiten einer generischen ATS-Vorlage mit „6 MCP-Tools“ [S]. Als Beleg ungeeignet. |

## 2. APIs, SDKs und die „Lücke“

| Aussage | Urteil | Befund |
|---|---|---|
| Für die Jobsuche gibt es ein vollständig dokumentiertes OpenAPI-Spec auf GitHub: `X-API-Key: jobboerse-jobsuche`, `/pc/v6/jobs`, `/pc/v4/jobdetails/{base64(refnr)}` | korrekt, mit Einschränkung | `openapi.yaml` v2.1.0 in bundesAPI/jobsuche-api bestätigt alle drei Angaben [P]. Das Antwortschema beschreibt aber noch das v4-Format (Korrektur 3). Zitiert wird fälschlich eine WorkAist-Seite. |
| ESCO: rund 3.000 Berufe und 14.000 Skills, Web-API und Local API | korrekt | ESCO v1.2 hat 3.039 Berufe und 13.939 Skills; v1.2.1 (Dezember 2025) ist ein Minor-Release [S]. Zitiert wird fälschlich ein R-Skript zur Jobsuche. |
| Es gibt einen offiziellen ESCO↔O*NET-Crosswalk, der jede ESCO-Occupation mit mindestens einer O*NET-Occupation verbindet | Crosswalk korrekt, Abdeckung nicht geprüft | Technischer Bericht und CSV liegen auf dem ESCO-Portal, außerdem gibt es die O*NET-Crosswalk-Seite [S]. „Jede ESCO-Occupation“ lässt sich nur mit der CSV prüfen [N]. |
| O*NET hat mehr als 19.000 Task Statements als Excel-Download | im Kern korrekt | Release 28.0 hat 19.281 Zeilen [S]. Für Release 31.0 ist die Zahl nicht geprüft. Neben Excel gibt es Text und SQL. Lizenz CC BY 4.0. Der Link führt auf Release 20.1 (veraltet). |
| KldB 2010: Struktur über metadaten.bibb.de, das Stata-Modul `kldbrecode` liefert Crosswalks zu ISCO und Berufsfeldern | korrekt | `kldbrecode` gibt es: Gerhardt & Kappes 2025, SSC s459442, KldB 2010 → KldB 1988, ISCO-08, BIBB-Berufsfelder, BAS-Prestige [P]. Amtliche Quelle ist die BA (Korrektur 6). |
| Für BERUFENET, ESCO und KldB gibt es keinen etablierten fertigen MCP-Server | teilweise korrekt | Offizielle Registry am 29.10.2026: 0 Treffer [P]. Es gibt aber unreife Server [P/S]: slopinger/arbeitsagentur-mcp (BERUFENET, Entgeltatlas, KURSNET; 1 Stern, 10/2026), Dembelinho/ESCO-MCP-Server, Richard-Ewing/careerwin-mcp (ESCO und O*NET), colaberry/WorldOfTaxonomy (ESCO, ISCO, O*NET, KldB; die KldB ist dort fehlerhaft), npm `@pipeworx/mcp-onet`, `german-arbeitsmarkt-mcp`, `mcp-bajobs`. |
| MCP Python SDK: FastMCP, `@mcp.tool()`, stdio/HTTP/SSE | veraltet | Siehe Korrektur 2. `@mcp.tool()` bleibt erhalten. Das separate Paket `fastmcp` (PrefectHQ, v4.1.4) baut auf `mcp>=2.3` auf [P]. |
| mcp-jobspy und mcp-stepstone scrapen kommerzielle Portale gegen deren AGB | korrekt | Scraping verbieten die LinkedIn User Agreement (§ 8.2), die Indeed Terms und die StepStone-Nutzungsbedingungen [S]. mcp-jobspy scrapt StepStone **nicht**. Ein AGB-Verstoß ist nicht automatisch rechtswidrig, birgt aber vertragliche Risiken und die Gefahr von Sperren. Indeed betreibt einen eigenen MCP-Server (Beta) [S]. |
| Cobrainer liefert Job-Architektur-Kontext per MCP, ~250.000 Skills, 15 Jahre | teils belegt | Die Cobrainer-Doku beschreibt einen MCP-Server mit Tools wie `get_role_profile`, `search_roles`, `assess_ai_automatability` und `generate_skill_file` [S]. Die Zahlen siehe Korrektur 10. Das Meeting-Transkript lag nicht vor [N]. |

## 3. Rohdaten, Referenzdaten, Statistik

| Aussage | Urteil | Befund |
|---|---|---|
| Jobsuche: öffentlicher JSON-Endpunkt, nur clientId als `X-API-Key`, keine Registrierung, Details per base64(refnr) | korrekt | Bestätigt [P]. Das Beispiel `10001-1002716922-S` ergibt `MTAwMDEtMTAwMjcxNjkyMi1T`; WorkMCP testet genau das. |
| Parameter `was`, `wo`, `umkreis`, `page`, `size` bis 100; Facetten | weitgehend korrekt | Die Parameter stehen in der Spezifikation [P]. Ein Maximum von 100 nennt das Spec nicht, das Beispielskript nutzt `size=100` [P]. |
| Rund 800.000 offene Stellen | nicht verifiziert | Der Wert stammt aus dem Titel eines dev.to-Artikels (821.306) und schwankt täglich [N]. |
| Common Crawl crawlt monatlich mehr als 1 Mrd. Seiten | korrekt | 2026 sind es rund 2,1 bis 2,3 Mrd. Seiten je Crawl (Mai 2026: 2,16 Mrd.) [S]. |
| StepStone/Indeed/XING/LinkedIn: keine offiziellen Scraping-APIs | korrekt | Siehe oben. |
| BERUFENET: über 3.500 Berufe mit „Aufgaben und Tätigkeiten“, frei zugänglich | korrekt | bundesAPI nennt rund 3.569 Berufe und 2.730 Tätigkeiten [P]. Dazu kommt die JSON-Schnittstelle (Korrektur 4). |
| KldB-Strukturdateien als PDF beim BIBB; KldB als Branchen-Overlay | falsch bzw. irreführend | Siehe Korrektur 6. |
| ESCO-API mit essential/optional-Relationen als Linked Open Data | korrekt | Die Relationen stehen im HAL-Format in `_links.hasEssentialSkill` und `_links.hasOptionalSkill` [S]. |
| O*NET Core/Supplemental, über Mappings auf deutsche Berufe übertragbar | korrekt mit Vorbehalt | Task-Typ und Befragungsdaten bestätigt [S]. O*NET beschreibt US-Berufe; eine Übertragung braucht fachliche Prüfung. |
| GENESIS: Verdienste nach WZ 2008 und Anforderungsniveau | plausibel | Die API braucht Registrierung bzw. Token (kostenlos) [S]. Für Gehälter nach Beruf ist der Entgeltatlas passender (Korrektur 5). |
| Rechtliche Fußnote: „Die Arbeitsagentur-API ist bewusst öffentlich dokumentiert“ | falsch | Dokumentiert hat sie die Community (bundesAPI), nicht die BA [P]. |

## 4. Nachtrag „weitere Quellen“

| Aussage | Urteil | Befund |
|---|---|---|
| Arbeitnow: kostenlos, kein Key, normalisierte ATS-Feeds, Filter für `remote` und `visa_sponsorship` | weitgehend korrekt | Kostenlos und ohne Key, `visa_sponsorship` bestätigt [S]. Einen Remote-Parameter fand ich nicht; WorkMCP filtert lokal über das Feld `remote`. |
| Adzuna: kostenloser Developer-Key, Gehalts-Histogramme, Top-Unternehmen, Gehaltsverlauf | korrekt | Die Endpunkte `histogram`, `top_companies`, `history` und `geodata` sind bestätigt [P, npm `adzuna-sdk`, dessen Schema auf der offiziellen Doku basiert]. Der Verlauf arbeitet mit Kategorie und Ort, nicht mit Stichwort [P]. |
| Adzuna als „einzige programmatische Gehaltsquelle“ | falsch | Der Entgeltatlas liefert amtliche Werte (Korrektur 5). |
| ATS-Job-Board-APIs ohne Auth je Firmen-Slug: Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workday, Personio-XML | korrekt | Alle am 04.08.2026 live verifiziert, dazu Workable und BambooHR [P, conorscode/ats-api-reference]. Workday braucht die Karriereseiten-URL (Tenant, Shard, Site); Personio leitet bei Nicht-Kunden mit 307 um. |
| Personio-Feed mit `department`, `employmentType`, `seniority`, `yearsOfExperience` | teilweise verifiziert | `department` und `employmentType` stehen im Referenzbeispiel [P]. `seniority` und `yearsOfExperience` entsprechen dem Personio-Schema, im gekürzten Beispiel fehlen sie. WorkMCP liest alle vier aus. |
| Interamt: REST-API nur zum Einpflegen, Lesen nur über Portal oder Scraping | plausibel | Nicht integriert [S]. |
| Apify-Actor „nur neue Jobs seit letztem Lauf“ | – | Kostenpflichtig, nicht integriert. Dieselbe Funktion liefert WorkMCP über das Delta-Gedächtnis (`nicht_mehr_enthalten`/`neu`) kostenlos. |
| StepStone/GEHALT.de: über 1,3 Mio. Vergütungsdaten, Median 53.900 € | nicht verifiziert | Keine API [N]. |
| IAB-Stellenerhebung (Zugang über das FDZ), BIBB-FDZ, GENESIS | plausibel | Das sind Forschungsdatenzugänge, keine APIs [S]. |
| XING: E-Recruiting-API nur für Kunden zum Schalten von Stellen; LinkedIn und Indeed ohne öffentliche Lese-API | plausibel | Indeed hat einen MCP-Server in der Beta [S]. |
| „BERUFENET/KURSNET: nur XML-Upload, kein Lesen“ | falsch | Beide lassen sich lesen: BERUFENET über `infosysbub/bnet`, KURSNET/mein NOW über `rest.mein-now.de/now-prod/suche` (inoffiziell) [P, Code von slopinger/arbeitsagentur-mcp]. |
| Quellenangaben im Nachtrag | verschoben | Die XING-Aussage zitiert fdz.iab.de, die BERUFENET/KURSNET-Aussage dev.xing.com. |

---

## Anhang: Prüfung des Prototyps `berufsgraph-mcp`

**Übernommen:**

- `get_role_context`: Rolle, Aufgaben, Skills und Marktsignal in einem Aufruf.
- Das Marktsignal als reine Zählung.
- Registrierungsbeispiele für mehrere Harnesses.
- Abschnitte über Überschriften wie „Aufgaben und Tätigkeiten“ erkennen.
- Graph-Export für Neo4j und NetworkX.
- Ehrliche Liste der Limitierungen.

**Nicht übernommen, weil im Live-Betrieb fehlerhaft:**

| Stelle | Problem |
|---|---|
| `server.py:8` | `from mcp.server.fastmcp import FastMCP` mit `mcp[cli]>=1.2.0` ohne Obergrenze. Mit dem aktuellen SDK 2.x startet der Server nicht. |
| `jobsuche.py:9` | Im Basis-URL fehlt `/jobboerse/jobsuche-service`. |
| `jobsuche.py` | Liest `_embedded.positions`, `aktualisierungsdatum` und `details_url`. Diese Felder gibt es nicht, die Gesamtzahl steht in `maxErgebnisse`. |
| `jobsuche.py` | Default `angebotsart=4` bedeutet nur Ausbildung bzw. duales Studium, auch beim Marktsignal. |
| `esco.py` | Nutzt `esco.ec.europa.eu/api` statt der dokumentierten `ec.europa.eu/esco/api`. Die Skills sucht er in `essentialSkillsUris`, sie stehen aber in `_links.hasEssentialSkill`. Ergebnis: leere Listen. |
| `crosswalk.py:39` | KldB→ESCO sucht den KldB-Code als Freitext in ESCO. |
| `berufenet.py` | HTML-Scraping einer Single-Page-App; die JSON-Schnittstelle wird übersehen. |
| `data/kldb_seed.csv` | Fachlich falsche Codes: eine Berufshauptgruppe 13 gibt es in der KldB 2010 nicht, Softwareentwicklung liegt in 434, nicht in 251. |
| `cache.py` | Überschreibt nach Ablauf der TTL ohne Versionierung und Delta, erfüllt also „merken und ergänzen“ nicht. |
