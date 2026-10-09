# NorthBridge Garments — Production Event Dashboard

A Django-based dashboard for managing production events from garment production lines.

The system supports `COUNT` and `VOID` events, validates event data, tracks production totals, and monitors acknowledgements and exceptions. SQLite is used by default, so no separate database server is required.

## Features

* Production dashboard with total counts and processed events.
* REST API for submitting single or multiple events.
* Duplicate event detection.
* Invalid event validation and audit history.
* `VOID` events to correct previous `COUNT` events.
* MQTT challenge worker running in a separate process.
* Django Admin for managing and viewing events.
* SQLite and PostgreSQL support.
* Automated tests for important business rules.

## Requirements

* Python 3.10 or later
* Windows PowerShell
* Git (optional)

## Installation

Open PowerShell and run:

```powershell
cd "E:\Django Task\EPD\iot_dashboard"

py -m venv .venv

.\.venv\Scripts\python.exe -m pip install --upgrade pip

.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Copy-Item .env.example .env
```

## Run the Project

Run database migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

Start the development server:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Open the dashboard:

http://127.0.0.1:8000

Select **COUNT +5 (LINE-01)** and click **Submit** to create a sample event.

## API Endpoints

| Method | Endpoint                     | Description                   |
| ------ | ---------------------------- | ----------------------------- |
| POST   | `/api/events`                | Submit production events      |
| GET    | `/api/state?view=summary`    | View production summary       |
| GET    | `/api/state?view=pending`    | View pending acknowledgements |
| GET    | `/api/state?view=exceptions` | View event exceptions         |
| POST   | `/api/ack`                   | Acknowledge processed events  |

## Event Types

### COUNT

A `COUNT` event adds production quantity to the total.

Example:

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

The quantity must be an integer between 1 and 500.

Submit a COUNT using PowerShell:

```powershell
$count = @{
  source_id = "LINE-01"
  event_id = "EV-101"
  type = "COUNT"
  quantity = 5
  target_event_id = $null
  event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/events" `
  -ContentType "application/json" `
  -Body ($count | ConvertTo-Json)
```

`POST /api/events` also accepts an array of event objects. Each item receives an independent result.

### VOID

A `VOID` event corrects a previous `COUNT` event.

* The target event must belong to the same production line.
* Only one valid `VOID` is allowed per `COUNT`.
* The original event is kept in the database.
* The corrected quantity is removed from the net production total.

The system can also resolve a `VOID` received before its target `COUNT`.

Submit a VOID for an existing COUNT:

```powershell
$void = @{
  source_id = "LINE-01"
  event_id = "EV-VOID-101"
  type = "VOID"
  quantity = $null
  target_event_id = "EV-101"
  event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/events" `
  -ContentType "application/json" `
  -Body ($void | ConvertTo-Json)
```

## Event Statuses

* `ACCEPTED` — Event accepted and processed.
* `DUPLICATE` — Event already exists.
* `CONFLICT` — Same event ID with different data.
* `PENDING_REFERENCE` — Target event has not arrived yet.
* `REJECTED` — Invalid event or business rule violation.

## Acknowledgement

Processed `COUNT` events can be acknowledged through the dashboard or the `/api/ack` endpoint.

```powershell
$body = @{ event_ids = @("EV-101") } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/ack" `
  -ContentType "application/json" `
  -Body $body
```

Read summary, pending, and exceptions (optionally scoped to a source):

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=summary"
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=pending&source_id=LINE-01"
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=exceptions&source_id=LINE-01"
```

## MQTT Worker (Optional)

Configure your MQTT broker settings and `CANDIDATE_ID` in `.env`.

Run the worker in a separate PowerShell window:

```powershell
.\.venv\Scripts\python.exe manage.py run_mqtt_worker
```

The worker subscribes to `fse-01/{CANDIDATE_ID}/challenge`, publishes challenge responses to `/response`, and publishes `ONLINE`, `HEARTBEAT`, and `OFFLINE` status to `/status`. The dashboard and worker use the same database. MQTT is optional for normal REST API usage.

With the worker running, create a current challenge payload in PowerShell. Set the candidate ID to the one assigned for your broker:

```powershell
$now = [DateTime]::UtcNow
$candidateId = "CAND-XXX"
$challenge = @{
  protocol_version = "1.0"
  candidate_id = $candidateId
  challenge_id = "CH-DEMO-001"
  command = "PROCESS_EVENTS"
  expires_at = $now.AddMinutes(5).ToString("yyyy-MM-ddTHH:mm:ssZ")
  events = @(@{
    source_id = "LINE-01"
    event_id = "EV-MQTT-001"
    type = "COUNT"
    quantity = 6
    target_event_id = $null
    event_time = $now.ToString("yyyy-MM-ddTHH:mm:ssZ")
  })
}
$payload = $challenge | ConvertTo-Json -Depth 6 -Compress
```

With `mosquitto_pub` installed, set `$brokerHost` and publish to the worker:

```powershell
mosquitto_pub -h $brokerHost -p 1883 -q 1 `
  -t "fse-01/$candidateId/challenge" -m $payload
```

Use the broker port and TLS/authentication options matching `MQTT_URL`. Replaying the same challenge ID with the identical body returns the saved response without processing the event again.

The dashboard and worker use the same database. MQTT is optional for normal REST API usage.

## Django Admin

Create an administrator account:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Open:

http://127.0.0.1:8000/admin/

## Run Tests

Run the automated test suite:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

The eight tests cover COUNT 500/501 validation and total, REST and MQTT rejection consistency, duplicate delivery, `VOID` resolution, repeated acknowledgements, MQTT challenge replay, conflict handling, and filtering a source that has only rejected submissions. They use SQLite and do not require a live broker.

**Latest recorded result:** 8 tests passed; Django system checks reported no issues.

## PostgreSQL (Optional)

PostgreSQL can be enabled by updating the database settings in `.env`.

```dotenv
DB_ENGINE=postgresql
PGDATABASE=northbridge
PGUSER=postgres
PGPASSWORD=your-password
PGHOST=127.0.0.1
PGPORT=5432
```

Create the database with your PostgreSQL administrator account:

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE northbridge;"
```

Set `DB_ENGINE=postgresql` and your database credentials in `.env`, then run migrations:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

## Documentation

* `TECHNICAL_EXPLANATION.md` — Technical design and business logic.
* `AI_USAGE.md` — AI assistance details.
* `AI_CONVERSATION_RECORD.md` — Work conversation record.
* `evidence/` — Dashboard and REST screenshots, API responses, and local MQTT-handler replay evidence. The MQTT handler evidence is not a live broker capture.

Build the clean source archive (excludes virtual environments, caches, local database, `.env`, and Git history):

```powershell
.\.venv\Scripts\python.exe evidence\build_source_zip.py
```

The archive is `dist/EPD-source.zip`.

## Technologies Used

* Python
* Django
* SQLite
* PostgreSQL
* MQTT
* PowerShell

---

**Project:** NorthBridge Garments — Production Event Dashboard
