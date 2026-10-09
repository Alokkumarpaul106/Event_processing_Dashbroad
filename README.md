# NorthBridge Garments — Production Event Dashboard

গার্মেন্টসের production line থেকে `COUNT` ও `VOID` event গ্রহণ, যাচাই এবং পর্যবেক্ষণের জন্য Django dashboard। SQLite ডিফল্ট database, তাই আলাদা database server ছাড়াই লোকালভাবে চালানো যায়।

## কী কী আছে

- Production total, processed event, acknowledgement ও exception দেখার dashboard
- একক event বা event-এর batch গ্রহণের REST API
- Duplicate ও ভুল event শনাক্তকরণ এবং submission audit history
- `VOID` দিয়ে আগের `COUNT` সংশোধন; আগে আসা `VOID`-ও পরে সংশ্লিষ্ট `COUNT` এলে resolve হয়
- আলাদা process-এ চালানো যায় এমন MQTT challenge worker
- Admin site-এ event, attempt ও MQTT challenge দেখার সুবিধা

## প্রয়োজনীয় সফটওয়্যার

- Python 3.10 বা তার পরের সংস্করণ
- Windows PowerShell (নিচের setup নির্দেশনার জন্য)

## ইনস্টল ও চালানো

PowerShell-এ project folder-এ যান:

```powershell
cd "E:\Django Task\EPD\iot_dashboard"
```

Virtual environment তৈরি করে dependency ইনস্টল করুন:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Database migration চালিয়ে development server শুরু করুন:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Browser-এ <http://127.0.0.1:8000> খুলুন। Dashboard-এ **COUNT +5 (LINE-01)** বেছে **Submit** চাপলে একটি sample event জমা হবে। একই event আবার পাঠালে `DUPLICATE` দেখানো স্বাভাবিক।

> `.env`-এ local database-এর জন্য SQLite আগে থেকেই সেট করা আছে। MQTT worker চালু না করলেও dashboard ও REST API ব্যবহার করা যাবে।

## API দিয়ে sample data পাঠানো

Server চালু রেখে আরেকটি PowerShell খুলুন। নিচের উদাহরণে event ID `EV-DEMO-001`; প্রতিবার নতুন event পরীক্ষা করতে `event_id` বদলে দিন।

```powershell
$payload = @{
  source_id = "LINE-01"
  event_id = "EV-DEMO-001"
  type = "COUNT"
  quantity = 5
  target_event_id = $null
  event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}

$body = $payload | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/events" `
  -ContentType "application/json" `
  -Body $body
```

`POST /api/events`-এ একাধিক event-ও পাঠানো যায়। প্রতিটি item-এর জন্য আলাদা ফল আসে:

```powershell
$batch = @(
  @{ source_id = "LINE-01"; event_id = "EV-BATCH-1"; type = "COUNT"; quantity = 3; target_event_id = $null; event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ") },
  @{ source_id = "LINE-01"; event_id = "EV-BATCH-2"; type = "COUNT"; quantity = 4; target_event_id = $null; event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ") }
)
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/events" `
  -ContentType "application/json" `
  -Body ($batch | ConvertTo-Json)
```

সারাংশ দেখতে:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=summary"
```

গুরুত্বপূর্ণ API route:

| Method | Route | কাজ |
| --- | --- | --- |
| `POST` | `/api/events` | একটি event বা event-এর array জমা দেয় |
| `GET` | `/api/state?view=summary` | মোট হিসাব ও MQTT অবস্থা দেখায় |
| `GET` | `/api/state?view=pending` | acknowledgement-এর অপেক্ষায় থাকা event দেখায় |
| `GET` | `/api/state?view=exceptions` | unresolved, rejected ও conflict event দেখায় |
| `POST` | `/api/ack` | processed event acknowledge করে |

কোনো নির্দিষ্ট line-এর তথ্য পেতে `source_id` যোগ করুন, যেমন:
`/api/state?view=pending&source_id=LINE-01`।

তিনটি state view-এর request:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=summary"
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=pending&source_id=LINE-01"
Invoke-RestMethod "http://127.0.0.1:8000/api/state?view=exceptions&source_id=LINE-01"
```

## Event-এর নিয়ম

`COUNT` event-এর জন্য `source_id`, `event_id`, 1 থেকে 500-এর মধ্যে পূর্ণসংখ্যা `quantity`, এবং timezone-সহ ISO 8601 `event_time` দিতে হবে। `target_event_id` ফাঁকা বা `null` থাকবে। 500-এর বেশি হলে event `REJECTED` হবে এবং rejected-submission summary-তে গণনা হবে।

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

`VOID` event-এ `quantity` ফাঁকা বা `null` থাকবে এবং `target_event_id`-এ যে `COUNT` সংশোধন করতে হবে তার ID দিতে হবে। দুই event-এর `source_id` একই হতে হবে। একটি `COUNT`-এর জন্য কেবল একটি valid `VOID` গ্রহণ করা হয়। সংশোধনের জন্য মূল event মুছে ফেলা হয় না; net total থেকে তার পরিমাণ বাদ পড়ে।

আগের উদাহরণের `EV-DEMO-001` COUNT-কে reverse করতে:

```powershell
$void = @{
  source_id = "LINE-01"
  event_id = "EV-VOID-001"
  type = "VOID"
  quantity = $null
  target_event_id = "EV-DEMO-001"
  event_time = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
}
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/events" `
  -ContentType "application/json" `
  -Body ($void | ConvertTo-Json)
```

API result-এর status:

- `ACCEPTED` — event গৃহীত ও process হয়েছে
- `DUPLICATE` — একই event আগে জমা হয়েছে
- `CONFLICT` — একই ID-তে ভিন্ন event data এসেছে
- `PENDING_REFERENCE` — `VOID` এসেছে, কিন্তু target `COUNT` এখনও পাওয়া যায়নি
- `REJECTED` — event-এর data বা নিয়মে সমস্যা আছে

## Acknowledgement

Dashboard-এর **Pending acknowledgement** তালিকা থেকে processed `COUNT` বেছে **Acknowledge selected** চাপুন। API দিয়ে করতে:

```powershell
$body = @{ event_ids = @("EV-DEMO-001") } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/ack" `
  -ContentType "application/json" `
  -Body $body
```

## MQTT worker (ঐচ্ছিক)

`.env`-এ broker এবং আপনার `CANDIDATE_ID` সেট করুন। Web server চালু রেখে **দ্বিতীয় PowerShell**-এ চালান:

```powershell
.\.venv\Scripts\python.exe manage.py run_mqtt_worker
```

Worker `fse-01/{CANDIDATE_ID}/challenge` topic-এ subscribe করে, `/response` topic-এ উত্তর দেয় এবং `/status` topic-এ connection status পাঠায়। Dashboard ও worker একই database ব্যবহার করে। Worker বন্ধ থাকলেও REST API-তে event জমা দেওয়া যায়।

## PostgreSQL ব্যবহার

`.env`-এ database settings পরিবর্তন করুন:

```dotenv
DB_ENGINE=postgresql
PGDATABASE=northbridge
PGUSER=postgres
PGPASSWORD=your-password
PGHOST=127.0.0.1
PGPORT=5432
```

PostgreSQL service চালু করে database তৈরি করুন (প্রয়োজনে `postgres`-এর বদলে আপনার admin user দিন):

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE northbridge;"
```

তারপর `.env`-এ database settings বদলে migration চালান:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

## Admin site

Admin user তৈরি করে <http://127.0.0.1:8000/admin/> খুলুন:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Automated tests

Project root থেকে automated suite চালান:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Suite-এ COUNT-এর 500/501 boundary ও total, duplicate delivery, আগে আসা VOID resolution, repeated acknowledgement, MQTT challenge replay, conflict handling, rejected-only source filter, এবং MQTT-তে COUNT 501 rejection পরীক্ষা করা হয়। Tests default SQLite test database ব্যবহার করে এবং বাইরের MQTT broker-এ connect করে না। শেষ যাচাইয়ে আটটি test pass করেছে।

## MQTT challenge example

Worker চালু থাকলে publisher `fse-01/{CANDIDATE_ID}/challenge` topic-এ এই shape-এর JSON পাঠায়। `candidate_id` নিজের assigned ID দিয়ে এবং দুই timestamp current UTC time দিয়ে দিন। একই challenge পুনরায় এলে worker stored response `/response` topic-এ আবার পাঠায়, কিন্তু event দ্বিতীয়বার process করে না।

```powershell
$now = [DateTime]::UtcNow
$candidateId = "CAND-XXX" # Replace with your assigned ID.
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

With `mosquitto_pub` installed and `$brokerHost` set to your broker host, publish it with:

```powershell
mosquitto_pub -h $brokerHost -p 1883 -q 1 `
  -t "fse-01/$candidateId/challenge" -m $payload
```

Worker challenge topic-এ subscribe করে, response topic-এ JSON ফল publish করে, এবং status topic-এ `ONLINE`, `HEARTBEAT`, ও `OFFLINE` status publish করে। Broker host, port, TLS এবং optional username/password `.env`-এর `MQTT_URL` থেকে আসে।

## Design notes

Entity model, shared REST/MQTT business logic, transaction boundaries, replay handling এবং operational assumptions-এর ব্যাখ্যা [TECHNICAL_EXPLANATION.md](TECHNICAL_EXPLANATION.md)-এ আছে। AI সহায়তার বিবরণ [AI_USAGE.md](AI_USAGE.md) এবং এই কাজের সংক্ষিপ্ত record [AI_CONVERSATION_RECORD.md](AI_CONVERSATION_RECORD.md)-এ রাখা হয়েছে।

## Assessment files

Dashboard, REST API, test-run এবং local MQTT handler evidence `evidence/` folder-এ আছে। Source archive তৈরি করতে:

```powershell
.\.venv\Scripts\python.exe evidence\build_source_zip.py
```

Archive হবে `dist/EPD-source.zip`; এতে environment, local database, `.env`, cache, এবং Git history অন্তর্ভুক্ত হয় না।
