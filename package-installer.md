# Pacchetto di installazione — piano

Obiettivo: rendere `pix3lcode` installabile con `pipx` invece che tramite
`.venv/bin/python` + `pix3lcode.sh`/`setup.sh` a mano dentro la cartella del
repo.

## Perché pipx (e non le alternative)

Opzioni valutate:

- **pip/pipx package** (scelta) — standard per CLI Python, pipx crea e
  gestisce da solo un venv isolato, comando finisce nel `PATH` dell'utente.
  Nessun refactor pesante richiesto, il codice è già quasi pronto.
- **Eseguibile standalone (PyInstaller/Nuitka)** — utile solo se serve
  distribuire a utenti senza Python installato. Più pesante da mantenere
  (build per OS/arch, import dinamici da dichiarare esplicitamente).
- **Pacchetto OS-nativo (.deb, Homebrew)** — ha senso solo puntando a un
  pubblico specifico via package manager di sistema. Overhead di
  manutenzione alto per un tool Python puro.
- **Script curl | bash** — più veloce da fare ma meno "pulito"; in pratica
  automatizza solo quello che oggi si fa a mano con `setup.sh`.

## Cosa va sistemato nel codice prima di pacchettizzare

File già a posto (nessuna modifica richiesta): `session.py`, `context.py`,
`agent.py`. Usano già path basati su `~` o `cwd`, non sul path dello script.

Da modificare:

1. **`config.py:46` — `PROFILES_DIR`**
   Oggi: `os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")`.
   Da installato in `site-packages` questo path esiste solo se `profiles/*.json`
   viene dichiarato come *package data*. Sostituire con `importlib.resources`
   per localizzare le risorse dentro il pacchetto installato.

2. **`tools.py:386` — iniezione di `.venv/bin` in `execute_shell`**
   Oggi calcola `.venv/bin` accanto allo script e lo antepone al `PATH` dei
   comandi shell lanciati dall'agente. Con pipx il venv non è più accanto al
   codice ma sepolto in `~/.local/pipx/venvs/...`. Da rendere condizionale
   (controllare `sys.prefix`) o rimuovere: ha senso solo in modalità
   "dev da sorgente".

3. **Struttura import**
   Oggi flat: `import tools`, `import git_tools`, `import web_tools`,
   `from config import AppContext`. Vanno raggruppati in un package vero
   (es. `pix3lcode/`) con import relativi (`from . import tools`), altrimenti
   da installati rischiano collisioni con moduli di terze parti.

4. **`pyproject.toml` (nuovo file)**
   - `[project]`: nome, versione, dipendenze (portate da `requirements.txt`)
   - `[project.scripts]`: mappa il comando `pix3lcode` alla funzione `main()`
     e (opzionale) `pix3lcode-setup` all'attuale `setup.py`
   - Sostituisce `pix3lcode.sh` e `setup.sh`, che diventano superflui

5. **Versionamento**
   Aggiungere `__version__` e un flag `--version` a `main.py` (oggi assente).

## Come funzionerà l'installazione (esperienza utente finale)

- **Prerequisito** (una tantum): `pipx` installato
  (`sudo apt install pipx` oppure `python3 -m pip install --user pipx`).

- **Installazione**, a seconda di dove viene distribuito il pacchetto:
  - da repo git: `pipx install git+https://.../pix3lcode.git`
  - da wheel costruito localmente: `pipx install pix3lcode-0.1.0-py3-none-any.whl`
  - modalità sviluppo (modifiche live sul proprio checkout):
    `pipx install -e .` lanciato dentro la cartella del progetto

- pipx crea un venv isolato in `~/.local/pipx/venvs/pix3lcode`, installa
  dentro tutte le dipendenze (`openai`, `rich`, `pypdf`, `PyYAML`, ecc.) e
  mette un eseguibile `pix3lcode` in `~/.local/bin` (deve essere nel `PATH`;
  `pipx ensurepath` lo sistema una volta sola).

- Da quel momento, **da qualunque directory**:
  - `pix3lcode-setup` per la configurazione iniziale
    (crea `~/.pix3lcode_config.json` come oggi)
  - `pix3lcode` per avviarlo — niente più `cd` nel repo o attivazione
    manuale del venv

- **Aggiornamento**: `pipx upgrade pix3lcode`

- **Disinstallazione**: `pipx uninstall pix3lcode` — pulita, nessun residuo

- Config, profili custom e sessioni restano dove sono oggi
  (`~/.pix3lcode_config.json`, `~/.pix3lcode_sessions/`). Solo i profili di
  *default* spediti col tool (`profiles/*.json`) vengono impacchettati dentro
  il pacchetto Python invece che letti da una cartella accanto allo script.

## Checklist di esecuzione — completata il 2026-07-24

- [x] Riorganizzare i moduli in un package (`pix3lcode/`) con import relativi
- [x] Spostare `profiles/*.json` come package data, caricarli con `importlib.resources`
- [x] Rendere condizionale/rimuovere l'iniezione di `.venv/bin` in `execute_shell`
- [x] Scrivere `pyproject.toml` (deps da `requirements.txt`, entry point `pix3lcode`)
- [x] Aggiungere entry point `pix3lcode-setup` per l'attuale `setup.py`
- [x] Aggiungere `__version__` e flag `--version`
- [x] Rimuovere `pix3lcode.sh` e `setup.sh` (sostituiti dagli entry point)
- [x] Testare `pipx install -e .` in locale
- [x] Testare `pipx install` da wheel costruito (`python -m build`)
- [x] Aggiornare `README.md` con le nuove istruzioni di installazione

## Scoperte impreviste durante l'esecuzione

- **Chiave API esposta**: `profiles/openrouter.json` (gitignored, chiave OpenRouter
  reale) veniva incluso di default nel wheel dal glob `profiles/*.json`. Corretto
  con un allowlist esplicito in `[tool.setuptools.package-data]` (solo i 3 profili
  tracciati in git). Il wheel già costruito con la chiave dentro è stato cancellato.
- **Profili custom dopo l'installazione**: impacchettare `profiles/` come dati del
  pacchetto rompe il workflow documentato "aggiungi un JSON in `profiles/`" per
  un'installazione non-editable (non si scrive in `site-packages`). Aggiunta una
  directory utente `~/.pix3lcode_profiles/`, controllata *prima* dei profili
  integrati nel pacchetto — così un profilo personale continua a funzionare anche
  con `pipx install` da wheel, non solo in modalità editable.
- `httpx` era importato direttamente da `web_tools.py`/`setup.py` ma non era
  dichiarato in `requirements.txt` (probabilmente arrivava come dipendenza
  transitiva di `openai`/`tavily-python`). Aggiunto esplicitamente sia a
  `requirements.txt` sia a `pyproject.toml`.
- Aggiunti `dist/`, `build/`, `*.egg-info/` a `.gitignore` (mancavano).
