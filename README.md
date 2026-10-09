# NorthBridge Garments — Django Production Event Dashboard

A Django implementation of the NorthBridge production event dashboard in the supplied project archive. The dashboard, REST API, database, audit trail, acknowledgement flow, and MQTT challenge worker share the same event rules.

## Run locally on Windows

From this directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000>. SQLite is the default, so the dashboard runs without a separate database server. Edit `.env` and replace `CANDIDATE_ID` before connecting to the assessment broker.

To run the MQTT worker, keep the web server running and start a second terminal in this directory:

```powershell
python manage.py run_mqtt_worker
```

The worker subscribes to `fse-01/{CANDIDATE_ID}/challenge`, responds on `/response`, and publishes ONLINE, HEARTBEAT, and OFFLINE status messages on `/status`. Its status is saved in the shared database so the dashboard can show the connection from a separate process. Set `MQTT_ENABLED=false` to disable the worker.

## PostgreSQL

PostgreSQL is supported for persistent or multi-process deployments. Create a database, then set these values in `.env`:

```dotenv
DB_ENGINE=postgresql
PGDATABASE=northbridge
PGUSER=postgres
PGPASSWORD=your-password
PGHOST=127.0.0.1
PGPORT=5432
```

Run `python manage.py migrate` after changing the database configuration. PostgreSQL enables transaction-scoped advisory locks for concurrent COUNT and VOID submissions; SQLite uses database write locking and the same uniqueness constraints.

## REST API

- `POST /api/events` accepts one event object or an array. Each item receives an `ACCEPTED`, `DUPLICATE`, `CONFLICT`, `PENDING_REFERENCE`, or `REJECTED` result. Invalid items are audited and do not discard other items in the batch.
- `GET /api/state?view=summary` returns production totals and MQTT status.
- `GET /api/state?view=pending&source_id=LINE-01` returns processed events waiting for acknowledgement.
- `GET /api/state?view=exceptions` returns unresolved VOIDs, rejected submissions, and conflicts.
- `POST /api/ack` accepts `{"event_ids":["EV-101"]}` and returns one acknowledgement result per ID.

Example COUNT event:

```json
{
  "source_id": "LINE-01",
  "event_id": "EV-101",
  "type": "COUNT",
  "quantity": 5,
  "target_event_id": null,
  "event_time": "2026-10-09T10:30:00Z"
}
```

A VOID refers to a COUNT by `target_event_id`. If it arrives first, it is stored as unresolved and applied when the matching COUNT arrives on the same line. A COUNT can have only one valid VOID. Voids are automatically acknowledged once resolved.

## Data and administration

All production events and submission attempts are retained. Reversals add a VOID event; they do not delete or edit the original COUNT. Totals are calculated from database rows, and MQTT challenge responses are stored for safe replay. Create an admin user with `python manage.py createsuperuser`, then visit `/admin/` to inspect sources, events, attempts, and challenges.
