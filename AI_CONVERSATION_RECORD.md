# AI conversation record

This is an abridged record of the project work conversation, prepared from the user/assistant exchange. It is not a verbatim export of the chat platform transcript.

## User requests and supplied requirements

1. The user said the project was complete and requested a small modification to the current implementation, following a supplied change-request image. The image required COUNT quantity validation from 1 to 500, persisted rejected submissions, a source filter, and a rejected-submissions dashboard indicator, while preserving the existing architecture and MQTT/REST behavior.
2. The user asked whether everything was complete and supplied a second assessment image. It additionally required at least five automated tests, technical explanation, README setup/API/MQTT instructions, AI usage disclosure and conversation record, screenshots, a clean source ZIP, and submission through a Google Form.
3. The user asked to fill the missing requirements.

## AI actions

- Inspected the existing code and confirmed REST and MQTT share `dashboard.services.process_event`/`process_batch`.
- Added the 1–500 shared COUNT validation, rejected-submission summary field, MQTT response field, dashboard indicator, and source-filter support for sources present only in submission attempts.
- Added regression tests for the COUNT 500/501 boundary on REST and MQTT, duplicate delivery, pending VOID resolution, repeated acknowledgement, MQTT challenge replay, conflicting event IDs, and filtering a rejected-only source.
- Added or updated the project documentation to explain setup, PostgreSQL initialization, tests, MQTT flow, entities, transaction boundaries, replay handling, assumptions, and AI assistance.

## Verification and external evidence

`python manage.py test` completed with eight passing tests and no Django system-check issues. The MQTT automated tests call the challenge handler with the database; they do not prove connectivity to the assessment broker. The dashboard and REST API screenshots use a temporary local SQLite server. The MQTT screenshot is explicitly labeled as handler-level, not live-broker evidence. The Google Form submission still requires the provided form link.
