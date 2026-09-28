# V25.7 â€” Government jobs: automatic add + automatic details

## Pehle kya problem thi
1. `SmartOfficialAdapter` sirf **title + link** laata tha; baaki sab "See official notification" rehta tha.
2. `source_registry` ke sources ko chalane wala scheduler (`run_due_sources`) APScheduler se **connected nahi tha**.

## Ab kya hota hai
```
source_registry (active) --scheduler--> collector (title+link)
   --> NEW record? --> enrichment.py: notification PDF/page khol ke
       vacancies, dates, qualification, age, fee, pay level,
       selection process, ad number, apply link nikalta hai
   --> admin review queue (kabhi auto-publish nahi)
```

## Setup (3 steps)
```bash
cd backend
# 1. sources seed + dry-run (kuch save nahi hota) â€” kaunse sources sach me kaam kar rahe dekho
python -m scripts.setup_government_sources
# 2. jo sources records de rahe hain unhe active karo
python -m scripts.setup_government_sources --activate
# 3. .env me
INGESTION_REGISTRY_ENABLED=true
INGESTION_ENRICH_DETAILS=true
```
Restart ke baad har `INGESTION_REGISTRY_INTERVAL_MINUTES` (default 60) par due sources chalte hain.

Purane jobs (jinme sirf title+link hai) ke liye: `python -m scripts.backfill_enrichment 100`
(scheduler bhi har run me 30 jobs backfill karta hai).

## Naya state/organization add karna (code change nahi)
`POST /api/v1/government/sources` (admin) ya Admin â†’ Sources page:
```json
{"source_name":"UPPSC","official_url":"https://uppsc.up.nic.in/","collector_type":"official_html",
 "organization":"UPPSC","govt_level":"State","category":"State PSC","schedule":"daily","status":"disabled"}
```
Phir `POST /government/sources/{id}/validate`, `/run` (trial), aur sahi lage to `PATCH status=active`.

## Rules
- Enrichment sirf **blank / placeholder** fields bharta hai, existing value overwrite nahi karta.
- Sirf naye records enrich hote hain (duplicate par extra download nahi).
- PDF ke liye sirf usi official site ke links follow hote hain; private IPs block.
- Scanned (image-only) PDF me text nahi milta -> record title+link ke saath hi review me aata hai.
- `INGESTION_AI_ENRICHMENT=true` par regex se jo chhoot jaye (vacancies/qualification/deadline) wo LLM se nikalta hai.
- Har record ke description me likha hota hai kaunse fields auto-filled hain; reviewer verify karke publish kare.

## Files
new: `app/ingestion/services/enrichment.py`, `scripts/setup_government_sources.py`, `scripts/backfill_enrichment.py`, `tests/test_enrichment.py`
changed: `orchestrator.py`, `ingest.py`, `scheduler.py`, `core/config.py`, `.env.example`, `docker-compose.production.yml`

