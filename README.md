# GAMA Learn

Lokal-first platforma za učenje, verifikaciju i nadzor GAMA agenata.

## Šta sadrži

- katalog skillova/alata sa statusom i dokazom
- kviz, spaced repetition, kurikulum
- challenge/eval + LLM eval
- benchmark `with/without` skill (`bench20.py`, `bench_hard.py`)
- artifacts registry (`artifacts.py`)
- Sentinel: live log, deep probe, Telegram alerti (`sentinel.py`, `sentinel_fleet.py`)
- skill fix loop: propose → approve → apply → verify → rollback (`skillfix.py`)
- MCP server (11 alata), PWA UI

## Pokretanje

```bash
python3 server.py --port 8078 --host 0.0.0.0
```

Health: `GET /api/health`.

## Testovi

```bash
python3 -m py_compile server.py sentinel.py skillfix.py bench20.py bench_hard.py sentinel_fleet.py artifacts.py mcp_server.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/smoke.py http://127.0.0.1:8078
```

## Konfiguracija

Kopiraj `.env.example` u `.env` i postavi vrijednosti. Runtime state
(`state/`) se ne commit-uje; rebuild se radi timerima ili ručno.

## Principi

- dokaz prije tvrdnje (`PASS`/`FAIL`/`SKIP` + evidence)
- bez auto-apply bez odobrenja
- LLM predlaže, deterministički kod odlučuje
- mutating akcije (mail/WA/objava) samo na izričitu naredbu
