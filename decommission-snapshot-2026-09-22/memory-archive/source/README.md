# Memory Archive MVP Light

Local-first MVP light for a family memory archive focused on episodes, media ingest, and evidence-backed retrieval.

What works now:
- upload files and import local folders
- import conversations from generic/Telegram/WhatsApp-style JSON
- store media metadata in SQLite
- create people and episodes
- attach media to episodes
- attach messages to episodes
- browse a simple web UI
- search archive content
- ask short questions inside an episode with evidence-backed results

Current boundary:
- no heavy video generation
- no face clustering yet
- no OCR for scanned documents yet
- no free-form persona chat

Run locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8810
```
