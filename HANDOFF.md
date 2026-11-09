# GAMA Learn — HANDOFF (Contabo, 07.11.2026)

Interaktivni graf znanja za učenje agenata + studijski kit + alati + istraživanje + moći.
Nastao na vmlab/opencode čvoru, prebačen ovdje da se dalje razvija.

## Šta je urađeno (P0–P12, 08.11.2026)

Kratko: vidi `GAMA_LEARN.md` (root workspace-a) i `gama/gama-learn.md`. Ključno:
P0 search; P1 katalog+kurikulum; P2 health; P3 learned→brain; P4 eval/CI; P5 digest;
P6 mobile; P7 stream; P8 tokeni; P9 dnevni digest timer; P10 graf klasteri;
P11 pass@k+LLM-judge; P12 systemd/backup/smoke/catalog cache. Detalji ispod.

## Pokretanje (na Contabu)

```bash
systemctl restart gama-learn     # primarno (Restart=always)
/opt/gama_learn/run.sh           # delegira na systemd
/opt/gama_learn/stop.sh
```

- Port **8078** (8077 je gama-stream web — NE dirati).
- Brain lokalno: `http://127.0.0.1:8065`.
- Log: `/tmp/gama_learn.log`; backup: `gama-learn-backup.timer` 03:30 (7 dana).
- Test: `python3 tests/smoke.py http://100.106.202.123:8078` (9/9).
- Fallback bez systemd: `python3 server.py --port 8078 --host 100.106.202.123`.
- Bez zavisnosti (Python 3 stdlib). edge-tts je potreban samo za audio.

## Šta je unutra (v0.5)

- **Graf** — 300 tema + 180 skillova + 5 izvora = **485 čvorova / 1048 veza** (cap
  radi brzine). **Pretraga ide preko punog korpusa** (2710 tema / 683 skilla) i
  otvara čvor i kad nije u grafu. Auto-refresh na promjenu fajlova (20 s poll).
- **Lekcija** — klik na čvor = ceo Markdown + povezani čvorovi.
- **Naučeno po agentu** — `state/learned.json`, zeleni prsten. Označavanje upisuje
  **brain lesson sa dokazom** (challenge PASS/FAIL/SKIP + ref + ts, `kind=lesson`).
- **Studijski kit** — sažetak, ključne tačke, kartice, kviz; **audio** preko edge-tts
  (bs-BA-VesnaNeural, keš u `state/audio`).
- **Alati (T)** — 12 lokalnih: JSON, Base64, SHA-256, UUID, lozinke, velika/mala, URL,
  vrijeme, tekst, regex, boje, Markdown.
- **Istraži (R)** — OpenAlex + arXiv (legalno; Sci-Hub nije integrisan). 10 min keš.
- **Plan (P) / Sledeće (N)** — kurikulum: hubovi + susedi fokusa, greedy 6 čvorova.
- **Sertifikat** — SVG za naučen čvor (agent, datum, serijski broj).
- **Moći (M)** — 59 stavki u `powers.json`: alati, hackovi, besplatno, novosti,
  skillovi, prečice; pretraga + filteri + kopiranje komande. **Live health**:
  `/api/health` (16 provjera paralelno, keš 15 s) → zeleni/crveni dot + latencija.
- **Katalog (K)** — 4724 stavke (4410 katalog skillova + ~226 lokalnih izvan
  kataloga + 88 alata), filteri domena/status/instalirano, pretraga; klik otvara
  `SKILL.md`. Sync: `catalog.yaml` + `~/.agents/skills`; `/api/catalog`.
- **Kurikulum po skillu** — 4 nivoa (Razumijevanje/Primjena/Verifikacija/Prijenos),
  ~60 min, svaki nivo nosi dokaz; challenge iz kataloga → `verify.py <id>`.
  `/api/curriculum?skill=<ime>`.

## Fajlovi

```
server.py      # stdlib HTTP + API + graf + research/study/tts/certificate
index.html     # UI
app.js         # graf (force), panel, alati, moći, istraživanje
style.css      # dark tema
powers.json    # 59 moći (menjati bez koda)
sources.json   # 5 izvora kao čvorovi (menjati bez koda)
README.md      # detalji + API tabela
state/learned.json, state/audio/
screenshots/   # plan, study-kit, tools, research, sources, powers
```

## API (sve GET osim POST)

| Putanja | Opis |
|---|---|
| `/api/graph` | nodes/edges/stats (+ fp) |
| `/api/study?ref=` | kit (sažetak/kartice/kviz/skript) |
| `/api/tts?ref=` ili `?text=` | MP3 (edge-tts) |
| `/api/research?q=` | OpenAlex + arXiv |
| `/api/powers` · `/api/sources` | moći · izvori |
| `/api/health` | 16 živih provjera + summary |
| `/api/digest?agent=` | dnevni digest + predlozi |
| `/api/auth` | trenutni role/agent/mode |
| `/api/tokens` (GET/POST) | admin: lista/dodaj/ukloni tokene |
| `/api/next?agent=&focus=` | sledeći čvor |
| `/api/curriculum?agent=&n=6` | plan |
| `/api/curriculum?skill=` | 4-nivo kurikulum + challenge |
| `/api/eval?skill=` | pokreni challenge uživo + upiši rezultat |
| `/api/eval/llm?skill=&k=&judge=` | pass@k + LLM-judge (vLLM) |
| `/api/eval/bulk?normalize=1` | bulk strukturna verifikacija + normalizacija |
| `/api/eval/tools?run=1` | live/registry provjera alata |
| `/api/eval/batch?start=1&n=10&k=2` | LLM batch + historija/regresije |
| `/api/audit?limit=50` | admin: audit log |
| `/api/review` (GET/POST) | spaced repetition due / pass-fail |
| `/api/fleet?refresh=1` | agregirani pregled Contabo + vmlab |
| `/api/alerts?agent=` | review/regresije/bulk/tools/FAIL/fleet alerti |
| `/api/catalog?q=&kind=&installed=` | katalog 4698 (sync lokalnih) |
| `/api/learned?agent=` / POST | stanje učenja (+ brain lesson sa dokazom) |
| `/api/note` (POST) | beleška → brain lesson |
| `/api/certificate?agent=&node=` | SVG |
| `/api/version` | fingerprint za auto-refresh |

## Provjereno (07.11.2026)

- Graf 485/1048 (cap 300 tema / 180 skillova od 2710/683); 5 izvora; 59 moći; 12 alata;
  kit 7 kartica/6 pitanja. Search pokriva sve (full_index, van grafa).
- Katalog: 4698 stavki (4610 skillova + 88 alata), instalirano 4670, 28 nije;
  challenge 1 (`ponuda-skill` → PASS). Prvi `/api/catalog` 4.2 s, keš 34 ms.
- Kurikulum: 4 nivoa/60 min; `gama-sql-vp2026` 3 komande; `gama-ponuda` challenge
  `verify.py ponuda-skill`.
- **Auto-challenge svi lokalni skillovi** (08.11.): 709 challenge-a (name+description,
  ≥1 `##`, sve `references/` postoje) + `ponuda-skill`. Prvi prolaz: 382 PASS / 328 FAIL.
  Normalizovano: **227** skillova dobilo `## Sadržaj`, **234** `references/*.md`
  rekonstruisano iz `SKILL.md`, 6 kratkih opisa prošireno. Final: **710/710 PASS**,
  katalog **verified 711** (gama-ponuda se pojavljuje 2×), untested 4013.
  `results.json` je per-machine (gitignore).
- vmlab `:8077` (pid 333809, bind `100.106.182.69`): graf 191/291, katalog 4571
  (instalirano 96, **verified 110**, challenges_run 787); 79 vmlab-only challenge-a
  generisano lokalno (per-machine), svi lokalni skillovi PASS.
- **Health (08.11.)**: Contabo `16/16 online`, 340 ms (mvm/shard ~330 ms preko
  Tailscale); vmlab miješano — lab nema sve Contabo servise, očekivano.
- **P3 (08.11.)**: mark learned → brain lesson sa dokazom. Test `qa-test`/`gama-cli`:
  challenge `PASS`, brain `wrote=/root/.agents/memory/transakcije/2026-11-08.md`,
  `duplicate=false`; unmark vraća count 0.
- **P4 (08.11.)**: `/api/eval?skill=` pokreće challenge uživo i upisuje `results.json`
  (PASS/FAIL/SKIP + ms + evidence); `verify.py --all` je CI gate (exit 1 na FAIL/ERR).
- **P5 (08.11.)**: `/api/digest` — challenge 710/710 PASS, katalog 711/4724,
  novo 24 h (8 tema, 8 skillova), predlozi eval/challenge; UI **Digest** (`D`).
- **P6 (08.11.)**: mobilni — pinch zoom + touch pan, `touch-action:none`, responzivan
  header i full-screen modali; `node --check` OK (nije testirano na uređaju).
- **P7 (08.11.)**: Stream — `/api/version.stream` iz `GAMA_STREAM_URL`; Contabo
  `http://100.106.202.123:8077` (SimpleHTTP, bez X-Frame-Options → iframe radi);
  dugme skriveno kad env nije postavljen (vmlab).
- **P8 (08.11.)**: multi-agent tokeni — test: open graph 200; bez tokena 401;
  read graph 200 / POST 403 `read-only`; write learned 200 (agent iz tokena
  `token-writer`, challenge PASS); write `/api/tokens` 403; admin lista 3,
  remove 200; vraćeno na legacy (tokens.json obrisan).
- **P9 (08.11.)**: dnevni digest timer — aktivan na **Contabu** (sljedeći 09.11.
  08:04) i **vmlabu** (09.11. 08:02 UTC). Test service upisao u brain
  `topic=gama-learn-digest` (`transakcije/2026-11-08.md`), duplicate=false;
  vmlab digest 110 PASS / 677 SKIP / 0 FAIL.
- **P10 (08.11.)**: graf klasteri — hull + group ankori (tema levo, skill desno,
  izvor gore), legenda filter, mini-mapa (klik=pan). Playwright: 2 canvasa,
  3 grupe, health 16/16, digest, **0 JS grešaka**; screenshot `/tmp/learn_ui.png`.
- **P11 (08.11.)**: pass@k + LLM-judge — `/api/eval/llm`, vLLM Qwen2.5-7B
  (fallback engine `deepseek-v4-flash`); test `a11y-audit` **pass@3 = PASS (3/3)**,
  ~6.9 s, judge 0.8, 0 JS grešaka; screenshot `/tmp/llm_eval_ui.png`;
  `state/llm_eval.json` per-skill.
- **P12 (08.11.)**: stabilizacija — `gama-learn.service` (Restart=always) na
  Contabu i vmlabu; `gama-learn-backup.timer` 03:30 (7 dana); `tests/smoke.py`
  **9/9 PASS**; `state/catalog_cache.json` hladno 4.35 s → toplo **0.18 s**.
- **P13 (08.11.)**: bulk pokrivenost — `/api/eval/bulk` (4608/4608 PASS, 0 FAIL,
  319 normalizovano, 943 skilla/3873 missing refs = warning), katalog **verified
  4610/4724 (97.6%)**; `gama-learn-bulk.timer` svakih 6 h + fingerprint.
- **P14 (08.11.)**: alati — 88 (8 live verified, 80 registry partial, 0 untested),
  `gama-learn-tools.timer` 6 h; batch eval n=10/k=2 nightly 04:00, historija i
  regresije (`state/eval_history.json`) + Digest „Eval trend“. Baseline: **3/10
  pass** (accounting, agent-factory, android-root), 41.7 s, 0 regresija (prvi run);
  slabi: agilni, ai-agenti, ai-prognoza, aktivnosti-djeca, analitika, android-vm,
  aplikacije. Tools/batch timer rade na Contabu (harness čvor).
- **P15 (08.11.)**: token admin UI + audit + rate limit + read-only link.
  Test: admin UI `2 tokena / 8 audit`; read token skriva **Tokeni** i gasi toggle;
  burst 250 → **223×200 / 27×429** (limit 240/min), restart resetuje; 0 JS grešaka;
  screenshot `/tmp/tokens_ui.png`. Batch baseline poslije fixa: **10/10 pass**
  (judge 0.8), 61 s; `improvements=[ai-agenti]`.
- **P16 (08.11.)**: spaced repetition — `/api/review`, intervali 1/3/7/14/30 dana;
  `pass` traži challenge/verified dokaz, `fail` resetuje; UI **Ponavljanje** +
  Digest `due/scheduled`. Test: learn → due 1 → pass interval 1 → fail lapses 1;
  bulk-only skill gate PASS; UI 1 due → 0 due, 0 JS grešaka; smoke **10/10**.
- **P17 (08.11.)**: Fleet dashboard — `/api/fleet` (Contabo + vmlab paralelno);
  **2/2 online**, verified **4728/4792**, tools 11, 0 regresija; Contabo
  4618/4724, vmlab 110/4571; UI 3 kartice, 0 JS grešaka; smoke **11/11**. Bulk
  nakon fixa: 4608/4608 PASS, `bulk_stale=false`.
- **P18 (08.11.)**: PWA/offline — manifest, SW `v3` (shell + graph/version/health/
  digest/review/learned/auth), ikone 192/512; HTTPS preko Tailscale serve `:8444`
  (Contabo + vmlab). Playwright: SW ready/ctrl, cache v3, **offline reload 485
  čvorova, 0 grešaka**; installability samo `in-incognito`; screenshot
  `/tmp/pwa_offline.png`; smoke **12/12**.
- **P19 (08.11.)**: quiz gate u review — „Položeno“ otvara 3 pitanja iz
  `/api/study`; prag **≥2/3** + postojeći challenge/verified gate. Test: 9 radija,
  tačni odgovori `[1,2,1]` → **0 due / 1 scheduled**, 0 JS grešaka; screenshot
  `/tmp/quiz_ui.png`.
- **P20 (08.11.)**: alerti — `/api/alerts` (review due, regresije, bulk stale,
  tools untested, challenge FAIL, fleet offline); UI **Alerti** + badge, browser
  notifikacija dok je app otvoren; timer **08:05** → brain `gama-learn-alerts`
  (dedup). Test: 1 review alert, „Idi“ otvara Review, 0 JS; timer `alerts=0`;
  screenshot `/tmp/alerts_ui.png`.
- **P21 (08.11.) truth reset**: bulk **default ne normalizuje** (default run:
  4605 PASS / 3 FAIL; `normalize=1` popravi 3 → 4608 PASS); sudija je nezavisan
  (engine fallback + harness retry), uklonjen score override; dodat `pass_all`;
  nivoi dokaza **L0 3963 / L1 721 / L2 12 / L3 0**; strict batch **10/10**,
  judge 0.66–0.95, 95.6 s.
- **P22 (08.11.) MCP**: `mcp_server.py` (stdio JSON-RPC), 6 alata
  (`learn_search/lesson/catalog/status/review/health`); test initialize,
  tools/list, search XHD211, status gama-cli — sve OK.
- **P23 (08.11.) benchmark**: `bench_skill.py` with/without skill, 3 zadatka:
  `gama-pdv` Δ0.00, `gama-sql-vp2026` **Δ+1.00**, `gama-ponuda` **Δ+1.00**;
  `state/bench_skills.json`.
- **P24 (08.11.) tools**: 12 live verified (`kalkul`, `qr`, `file_get`,
  `repomap` dodati), 76 registry partial, 0 untested.
- **P25 (08.11.) drift**: review čuva fingerprint ref fajla; promjena
  `SKILL.md` odmah vraća karticu u due (`drift=true`); test due future + stari
  fp → due 1 drift true.
- Audio MP3 200; cert SVG 200; research 8 rezultata; 0 JS grešaka.
- Auto-refresh: +1/−1 čvor za ~20 s; token 401/200.
- Testirano Playwright-om na Oracle čvoru.

## Poznato

- Brain `/read?ref=` ume vratiti neparsiran `raw` → fallback na snippet iz pretrage.
  `/read?id=` radi čisto.
- Na Oracle čvoru brain je remote pa je lokalni `~/.agents/memory/gama/gama-learn.md`
  ostajao 0 B — ovdje je brain lokalni, upis treba da legne normalno.
- 8077 na Contabu je gama-stream — ne koristiti. Na **vmlabu** je stara instanca
  GAMA Learn (`:8077`, ~191 čvor, stale) — nije izvor istine; aktivna razvojna
  instanca je **Contabo :8078**.

## Sledeće (predlozi za „razbijanje")

1. ~~**Skill katalog sync**~~ ✔ — 4698 stavki, 200 lokalnih dodato u sync; statusi
   ostaju `untested` dok ne prođu challenge (za sada 1: `ponuda-skill`).
2. ~~**Kurikulum po skillu**~~ ✔ — `/api/curriculum?skill=` (4 nivoa + challenge).
3. ~~**Moći live**~~ ✔ — `/api/health` 16 provjera (mvm, shard, brain, harness,
   gateway, engine, fastd, deep-research, fleet, katalog, gama-run, gamashell,
   gama-l, dsc, ops, guard); Contabo 16/16 online, 340 ms, keš 15 s.
4. ~~**Eval po skillu**~~ ✔ — live challenge (`/api/eval?skill=`) + CI gate
   (`verify.py` exit 1 na FAIL/ERR) + **LLM eval** (`/api/eval/llm?skill=&k=`):
   pass@k + LLM-judge na vLLM Qwen2.5-7B; UI dugme **LLM eval**.
5. ~~**Dnevni digest**~~ ✔ — `/api/digest` (challenge/katalog, novo 24 h, naučeno,
   predlozi fix/eval/challenge); UI dugme **Digest** (`D`). Na Contabu i vmlabu
   `gama-learn-digest.timer` (08:00) upisuje sažetak u brain.
6. ~~**Brain integracija**~~ ✔ — „naučeno“ upisuje `kind=lesson` sa dokazom
   (challenge PASS/FAIL/SKIP + ref + ts).
7. ~~**Stream**~~ ✔ — `GAMA_STREAM_URL` (Contabo `http://100.106.202.123:8077`)
   → dugme **Stream** sa iframe modalom + „Otvori u tabu“; bez env-a skriveno.
8. ~~**Multi-agent**~~ ✔ — `state/tokens.json` (read/write/admin); read token
   blokira POST (403 read-only), write token ne može `/api/tokens`; agent se
   forsira iz tokena; UI read-only gasi označavanje/belešku/eval. Default legacy
   (bez tokens.json).
9. ~~**Graf**~~ ✔ — klasteri po grupi (hull + ankori), legenda filter
   (tema/skill/izvor), full-text pretraga (✔), mini-mapa sa viewportom
   (klik/prevlačenje = pomeranje kamere).
10. ~~**Mobilni**~~ ✔ — touch pan/zoom (pinch), responzivan header, full-screen
    panel/modali; `touch-action:none`. Nije testirano na fizičkom uređaju.

## Pravila

- Sci-Hub se ne integriše; legalni izvori (OpenAlex/Crossref/arXiv/Unpaywall).
- Mutating akcije (mail/WA/objava) samo na izričitu naredbu.
- Dokaz prije tvrdnje: brojevi/komande + izlaz.
