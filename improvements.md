# Miglioramenti LLM CLI

## Alta priorità

- [ ] **Streaming della risposta** — il testo appare parola per parola invece di aspettare tutto insieme
- [x] **Conferma prima di eseguire shell** — chiede conferma per comandi rischiosi (`rm`, `sudo`, `kill`, ecc.)
- [x] **Tool `patch_file`** — modifica solo una parte di un file tramite sostituzione old→new univoca

## Media priorità

- [x] **Tool `search_files`** — cerca testo nei file con regex (come grep), così il modello può esplorare il codice
- [ ] **Multiline input** — con `Alt+Enter` per inviare blocchi di codice o testi lunghi
- [x] **Prompt di sistema configurabile** — modificabile tramite `llm_cli_config.json` senza toccare il codice

## Bassa priorità

- [x] **`/compact`** — riassume la conversazione per liberare contesto
- [x] **`/clear`** — cancella la cronologia e riparte da zero
- [x] **`/help`** — mostra tutti i comandi e i tool disponibili
- [x] **`/model`** — mostra il modello attivo e l'URL di LM Studio
- [x] **Salvataggio sessione** — auto-save dopo ogni scambio, `/sessions` per riprendere, `--resume` da CLI
- [x] **`/tokens`** — mostra i token usati nella sessione corrente (prompt, completion, totale)
- [x] **Contatore token** — mostrato automaticamente dopo ogni risposta
- [x] **Configurazione JSON** — `llm_cli_config.json` per URL, modello, timeout, soglie contesto e prompt
- [x] **Retry automatico** — backoff esponenziale (2s, 4s, 8s…) per N tentativi configurabili
- [x] **Timeout configurabile** — `api_timeout` e `api_retries` nel file di configurazione
- [x] **Troncamento intelligente** — avvisa quando il contesto supera la soglia configurata (default 70%)
- [x] **Profili** — `./llm.sh --profile coding` carica `profiles/coding.json` con modello e prompt dedicati
- [x] **Contesto di progetto** — legge `CONTEXT.md` dalla directory corrente e lo aggiunge al system prompt
- [x] **`/init`** — analizza il progetto e genera `CONTEXT.md` automaticamente
- [x] **Modalità non interattiva** — `./llm.sh "prompt"` risponde e termina; supporta pipe da stdin
