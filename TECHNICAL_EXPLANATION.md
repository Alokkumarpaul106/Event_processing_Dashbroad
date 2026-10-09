# Technical explanation

## Entity model

- `ProductionSource` represents a factory line or machine. Its `source_id` is the source key used by API filters.
- `ProductionEvent` is the durable production ledger. A row belongs to one source and has a source-scoped unique event ID. A COUNT has a positive integer quantity; a VOID points to the COUNT it reverses. A conditional unique constraint allows at most one VOID per source and target COUNT. The original COUNT is retained.
- `SubmissionAttempt` is the audit record for every processed delivery, including ACCEPTED, DUPLICATE, CONFLICT, PENDING_REFERENCE, and REJECTED results. Its JSON payload, source, event, channel, challenge ID, classification, reason, and receive time explain what arrived.
- `MqttChallenge` stores a canonical request digest and the complete response by challenge ID. It makes an identical broker replay return the original response.
- `MqttRuntimeState` stores the worker's last known connection, heartbeat, broker, candidate, and error information for the dashboard process.

## Module and function boundaries

- `dashboard.views` is the HTTP adapter. It decodes requests, validates API shape, calls the shared service functions, and serializes JSON responses.
- `dashboard.services.validate_event` owns event shape and business validation, including the COUNT quantity range of 1 through 500. `process_event` owns COUNT/VOID classification and persistence. `process_batch` applies that rule to each item. `submit_events` wraps REST batches in a transaction and emits domain signals after commit. The MQTT adapter calls `process_batch` directly inside its challenge transaction, so REST and MQTT do not copy the event rules.
- `dashboard.services.get_summary`, `get_pending`, and `get_exceptions` are the shared read functions used by state views. Summary values, including `rejected_submissions`, come from persistent rows and can be filtered by `source_id`.
- `dashboard.mqtt.handle_challenge_message` validates challenge metadata, checks replay identity, invokes the shared event service, and stores the response. `run_worker` owns broker connection, subscription, response publication, status heartbeat, and reconnect behavior.
- `dashboard.models` and migrations define durable entities, indexes, and uniqueness/check constraints. `dashboard.domain_events` exposes post-commit signals for future integrations.

## Transaction and duplicate strategy

The REST request processes its event array in one outer `transaction.atomic()` block. A malformed or out-of-range item is an ordinary REJECTED result with a persisted attempt; it does not prevent later items in that batch from being classified. A database failure rolls back the transaction. PostgreSQL deadlock and serialization errors are retried up to four times. PostgreSQL also uses transaction-scoped advisory locks around source/event or source/target keys. SQLite serializes writers and still uses the database uniqueness constraints.

The unique `(source, event_id)` constraint is the final race guard. If an event ID already exists, `_same_event` compares its normalized business fields and timestamp: identical content is DUPLICATE; different content is CONFLICT, and the first production row stays unchanged. The attempt row is kept in the same transaction as the event operation.

Acknowledgement uses a transaction and `select_for_update`. The first acknowledgement changes the row and returns ACKED; later calls see the saved timestamp and return ALREADY_ACKED.

## Pending VOID resolution

A VOID received before its COUNT is saved as `PENDING_REFERENCE` and audited. When the matching COUNT arrives on the same source, `process_event` marks that VOID `PROCESSED`, sets its resolution and acknowledgement timestamps, and reports the COUNT as accepted. Summary net total excludes any COUNT with a processed matching VOID. A VOID for a different source, a non-COUNT target, or a second VOID for an already-targeted COUNT is rejected without changing the production total.

## MQTT challenge trace and restart behavior

1. The worker subscribes to `fse-01/{CANDIDATE_ID}/challenge` with QoS 1.
2. `on_message` passes the payload to `handle_challenge_message`.
3. The handler validates protocol version, candidate ID, command, challenge ID, expiry, and events. It hashes canonical JSON and checks `MqttChallenge` under a transaction lock.
4. For a new challenge, the shared `process_batch` writes event rows and submission attempts. The handler computes the shared production summary and stores the complete response in `MqttChallenge` within the same outer transaction.
5. The worker publishes the saved response to `/response`. Its publish callback records `published_at`; connection and heartbeat details are saved for the dashboard.
6. After a restart or broker redelivery, the same challenge ID and digest returns the stored response without repeating event processing. Reusing a challenge ID with a different body returns CHALLENGE_CONFLICT.

The transaction stores the business result and response before network publication. QoS 1 and broker redelivery allow a response to be sent again after a restart. `published_at` is an observation of the client's publish callback, not a separate exactly-once guarantee from the broker.

## Future service split

The current function-based modular monolith keeps event rules, HTTP transport, MQTT transport, and persistence in separate modules while sharing one database transaction boundary. If deployment needs justify a split, keep `services.process_event` semantics behind a versioned event-processing interface first. A separate query/read module can own dashboard summaries, while REST and MQTT adapters remain thin. Moving MQTT to a worker service would require durable event delivery/outbox semantics and an explicit idempotency key across the service boundary; splitting the code alone would not provide those guarantees.

## Known assumptions and limits

- Source IDs identify lines/machines; event IDs are unique within a source, not globally.
- Event timestamps must be timezone-aware ISO 8601 strings. They are stored and serialized in UTC.
- A COUNT can be reversed by one valid VOID. A VOID does not delete the original event.
- The 1–500 COUNT limit is enforced by the shared REST/MQTT ingestion service. Direct database writes that bypass the service do not run that Python validation.
- PostgreSQL migrations are present, but this repository's automated suite uses SQLite. A live PostgreSQL instance is needed to verify PostgreSQL-specific advisory-lock behavior.
- The MQTT replay test exercises the challenge handler and database, not a live broker. Broker credentials and the assessment candidate ID must be supplied in the local `.env` file.
- Candidate ID is protocol routing/matching data; broker authentication and transport security depend on the configured broker URL and broker settings.
