# AI usage disclosure

OpenAI Codex assisted with the requested FSE-01 change and assessment preparation.

## AI-assisted work

- Inspected the existing Django models, service layer, REST views, MQTT challenge handler, dashboard, migrations, README, and Git state before editing.
- Updated the shared COUNT validator to accept only integer quantities from 1 through 500. The same service path is used by REST and MQTT.
- Added the persistent rejected-submission summary field, source-aware source options, dashboard indicator, and COUNT 501 demonstration control.
- Added Django regression tests for the required delivery and replay scenarios, plus event-ID conflict handling.
- Drafted the technical explanation, setup/test/MQTT README additions, and this disclosure/conversation record.

## Review and verification

The project test suite was run with `python manage.py test`: eight tests passed and Django reported no system-check issues. AI-generated changes should still be reviewed by the project owner before assessment or deployment. These tests use SQLite and do not connect to a live MQTT broker or PostgreSQL server. A separate live broker walkthrough and PostgreSQL run are needed when those services are available.

The example environment file contains placeholders only. Keep local `.env` files, broker credentials, candidate secrets, and database files out of Git and submission archives.
