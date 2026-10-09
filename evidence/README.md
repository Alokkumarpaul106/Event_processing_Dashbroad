# Assessment evidence

These captures were produced from a temporary SQLite database and a local Django server. They do not contain the developer's normal `db.sqlite3` or credentials.

- `dashboard.png` shows the updated dashboard populated through the REST API, including the seven indicators, a pending row, and the rejected COUNT value.
- `rest-api-results.png` and `rest-api-results.json` show actual HTTP responses for COUNT 500, duplicate delivery, COUNT 501 rejection, acknowledgement, and the filtered summary, pending, and exceptions views.
- `mqtt-challenge-results.png` and `mqtt-challenge-results.json` show the database-backed MQTT challenge handler accepting an event and returning the same stored response on replay. This is a handler-level check; it is **not** evidence of a connection to the assessment broker.
- `automated-tests.txt` records the Django test-suite run.
- `capture_local_mqtt_challenge.py` and `render_reports.py` regenerate the handler result and HTML reports when run against a configured local database.

For the required live MQTT screenshot, run the worker and publish a challenge using the assigned candidate ID and broker credentials. Do not submit the local-handler screenshot as proof of broker connectivity.
