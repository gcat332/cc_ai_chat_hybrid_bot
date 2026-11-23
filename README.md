# Thai call-center bot (ผู้ช่วยศูนย์บริการลูกค้า)

A rule-based Thai customer-service assistant, built in the spirit of
[huggingface/pybot](https://github.com/huggingface/pybot): plain Python, no model, no training,
no packages to install. Every answer comes from rules you can read, test and audit.

- **Phase 1 (this): web chat, by typing or by voice.** A chat page and a JSON API.
  Hold the mic button to talk (release to send), tap it for hands-free, or press the phone button for a
  phone-call screen.
- **Genesys Cloud phone line (voice bot):** callers talk to the bot in Thai on a real phone line
  through Genesys Audio Connector, with Azure for Thai speech. See
  [channels/audio_connector/README.md](channels/audio_connector/README.md).
- **Genesys Cloud chat:** the same bot behind Genesys through Bot Connector. Genesys handles calls,
  speech and agents. See [channels/genesys/README.md](channels/genesys/README.md).
- **Phase 2: phone line.** The same bot core behind telephony, speech-to-text and text-to-speech.
  See [channels/voice/README.md](channels/voice/README.md).

![Web chat demo](docs/webchat-demo.png) ![Call mode](docs/call-demo.png)

## Run it

Needs Python 3.8 or newer, nothing else.

```bash
python -m channels.webchat.server
```

Open http://localhost:8000. Demo data: phone `0812345678` with ID last 4 digits `1234`
(or `0898765432` / `5678`), and order numbers `123456`, `654321`, `111222`.

```bash
python -m unittest discover -s tests
```

## Public demo on GitHub Pages

GitHub Pages serves static files only, so there the same chat page runs the Python bot
**inside the visitor's browser** with [Pyodide](https://pyodide.org) (Python compiled to
WebAssembly). The first load takes a few seconds. The page shows "โหมดสาธิต" (demo mode).

1. Push this folder to a **public** GitHub repository, on the `main` branch.
2. In the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Each push to `main` runs `.github/workflows/pages.yml`: tests, then
   `tools/build_pages.py`, then deploy. The demo appears at
   `https://<your-user>.github.io/<repo-name>/`.

Browser mode is for demos only. Everything in it, including `backend.py`, is downloaded to the
visitor. Real customer data and API keys must stay on a server: run
`channels/webchat/server.py` in production. The same page then talks to it automatically.

## Talking by voice (in the browser)

The chat page uses the browser's own speech features (Web Speech API, `th-TH`). Nothing to
install, no API key, and it works on GitHub Pages.

- **Speak** (mic button), two ways:
  - **Press and hold** (push-to-talk): talk while holding, release to send. Pauses while holding
    are fine. The bot answers aloud and waits for you.
  - **Tap** (hands-free): talk, and it sends when you pause. After the bot answers aloud it listens
    again, so a whole conversation runs hands-free. Tap the mic again, type, or press a button to stop.
  - Talking over the bot interrupts it.
- **Call mode** (phone button): a phone-call screen. Talk back and forth with no buttons, like calling the
  call center:
  - The bot greets you and reads the menu, listens, answers aloud, then listens again.
  - When it asks for a phone, ID or order number, a **keypad** opens. Speak the number or type it
    and press ส่ง (like # on a phone).
  - **Mute**, **keypad** and **hang up** buttons, plus a call timer and live captions. The
    screen stays on during the call.
  - Silence: "ยังอยู่ในสายไหมคะ", then the bot hangs up politely. Asking for an agent shows the
    transfer. In this demo no real agent system is connected, so the call then ends.
  - The whole call appears in the chat afterwards.
  - If the mic cannot be used, the call continues with the keypad and buttons, and says why.
- **Numbers read the way an agent would:** phone, order and ticket numbers are read digit by
  digit ("ศูนย์ แปด หนึ่ง…"), money as "1250 บาท 50 สตางค์", and times as "8 นาฬิกา". The screen
  shows the text as written. Each reply carries a `speech` version for text-to-speech, which phase
  2 can reuse. Names TTS mispronounces go in `SAY_AS` in `config.py`.
- **Pace:** replies are spoken sentence by sentence with a short pause between, at normal (1.0×) speed
  by default. Choose ช้า / ปกติ / เร็ว in the header or on the call screen; the choice is
  remembered. The speech text has "." after each sentence and "," between phrases. Numbers are
  read back in groups (ศูนย์ แปด หนึ่ง, สอง สาม สี่, …), which also helps Genesys' text-to-speech.
- **Spoken replies** (speaker button): turned on automatically when you use the mic. Tap to switch off.
- Numbers said as words ("ศูนย์แปดหนึ่ง…", "หนึ่ง สอง สาม สี่") are understood as digits.

| Browser | Speak (mic) | Spoken replies (speaker) |
|---|---|---|
| Chrome, Edge (desktop and Android) | Yes | Yes |
| Safari (Mac, iPhone, iPad) | Yes | Yes |
| Firefox | No: the mic button is hidden, typing works | Yes |

Notes:
- The microphone needs HTTPS or `localhost`. GitHub Pages is HTTPS.
- Spoken replies need a Thai voice on the device. The bot never lets an English voice read Thai.
  Without a Thai voice it answers in text only and says how to add one. Most phones have one. On Windows, add the Thai
  language pack if the bot is silent.
- **Privacy (PDPA):** in Chrome and Edge, speech is sent to Google's or Microsoft's servers to be
  recognised. Say so in your privacy notice. If voice must stay within your own systems, use a
  speech-to-text service you contract instead (see the phase 2 plan).

## AI answers (optional, Claude)

The rules answer the topics below. For anything else ("สมัครสมาชิกยังไง", "ย้ายที่อยู่ต้องทำยังไง"),
the bot can ask Claude, and the answer is shown **and read aloud** like any other reply.

```bash
pip install -r requirements-ai.txt
export ANTHROPIC_API_KEY=...      # from https://platform.claude.com
python -m channels.webchat.server --ai
```

- **Rules first.** Identity checks, balances, orders, tickets and handoff never go to the AI. It
  sees no customer records and has no tools, so it cannot look up or change anything.
- **Instructions:** the system prompt in `callcenter_bot/ai_fallback.py` tells the AI to answer in
  Thai with ค่ะ/คะ, in 1–3 sentences that sound natural spoken, using only the company facts in
  `config.py`, and to offer an agent when unsure. Add your FAQ facts there.
- **Privacy:** phone and ID numbers are masked before anything is sent (`privacy.py`). Recent turns
  are sent too, so follow-up questions make sense.
- **Labelled:** AI answers show "ตอบโดย AI · อาจคลาดเคลื่อนได้" in the chat.
- **Safe failure:** if the API is down, slow (20 s timeout) or declines, the customer gets the
  usual "ยังไม่เข้าใจ" reply with the agent option. The chat never breaks.
- **Model:** `claude-opus-5-5` at low effort. To lower cost for high volume, change `MODEL` in
  `ai_fallback.py`, e.g. to `claude-haiku-5-5`, and test the Thai quality on your own questions.
- **Not on GitHub Pages:** the API key must stay on a server. The Pages demo is rules-only.

## Data tables (customers, balances, orders, cases, FAQ)

The bot reads and writes real tables in SQLite, which is part of Python, so there is nothing to
install:

| Table | What it holds |
|---|---|
| `customers` | phone, name, last 4 ID-card digits (for the identity check), outstanding balance, due date |
| `orders` | 6-digit order number, customer phone, status, carrier, tracking number, delivery date |
| `sn_customerservice_case` | cases the bot opened, **shaped like ServiceNow's Case table** (same name and fields: `sys_id`, `number` CS0001001…, `short_description`, `description`, `state`, `priority`, `category`, `contact_type`, `consumer`, `close_notes`, `opened_at`) plus `callback_phone` and `order_id` |
| `faq` | questions answered from data: topic, keywords customers say, the answer, and what to do after it (answer / offer a ticket / hand over). **The answers are examples: replace them with your real policies.** |

The tables are defined in `callcenter_bot/data/schema.sql`. Demo rows, including the test number
`0636538939` (ID last 4 digits `8939`), are in `callcenter_bot/data/seed.sql`; the example FAQ
in `seed_faq.sql`. A database made by an older version gets the new columns and the FAQ on start.

**Mock-data page** (for a POC on your own machine): every table, including the FAQ, on one page.

```bash
python -m dataadmin          # http://127.0.0.1:8100
```

Add, edit and delete rows, search, and reset everything to the demo rows. It edits the same
database as the chat and the Genesys endpoint, so the bot uses a change at once: edit an FAQ
answer and ask the question again. It listens on 127.0.0.1 only; to open it to others, set
`ADMIN_PASSWORD` and pass `--host 0.0.0.0`.

**Admin page `/admin`** (the clipboard button in the chat header): view, search, add, edit and delete rows, and
update case state. Changes are used by the bot straight away. Wrong input is refused with a
Thai message, e.g. a 9-digit order number.

- **Server:** the database is the file `data/callcenter.db`, created with the demo rows on first
  start (set `CALLCENTER_DB` to move it). The admin page needs a password:
  ```bash
  ADMIN_PASSWORD=choose-a-password python -m channels.webchat.server
  ```
  Then open http://localhost:8000/admin and sign in with user `admin`.
- **GitHub Pages:** the same tables run inside the browser, with no password. Changes are kept
  in that browser only. Other people don't see them, and "รีเซ็ตเป็นข้อมูลตัวอย่าง" restores
  the demo rows. Use the server for real customer data.
- To use your company's own systems instead, rewrite the functions in
  `callcenter_bot/backend.py`.

## Cases in ServiceNow

Requests the bot opens are cases. By default they go to the local table
`sn_customerservice_case`, which has the same name and fields as ServiceNow Customer Service
Management's Case table. To use a real instance instead, set on the server:

```bash
SERVICENOW_INSTANCE=https://yourcompany.service-now.com
SERVICENOW_USER=...          # integration user: read and create on sn_customerservice_case
SERVICENOW_PASSWORD=...
# optional
SERVICENOW_FIELD_MAP=callback_phone=u_callback_phone,order_id=u_order_number   # your custom fields
SERVICENOW_SKIP_FIELDS=category        # fields your instance's choice lists don't accept
```

The bot then opens cases with `POST /api/now/table/sn_customerservice_case` and reads them by
number with the Table API. If ServiceNow cannot be reached, the customer is handed to an agent
(`handoffReason=case_error`). Case states and what the bot says for each are in
`config.CASE_STATES`: the numbers are ServiceNow's usual ones (1 New, 10 Open, 18 Awaiting Info,
6 Resolved, 3 Closed, 7 Cancelled); check yours under System Definitions > Choice Lists.

Not yet tried against a real instance. `consumer` in ServiceNow is a reference to the consumer
record; until customers also come from ServiceNow, the verified phone is written into the
description. See `callcenter_bot/servicenow.py`. A database made by an older version moves its
`tickets` rows into the case table on start (TK1001 becomes CS0001001); customers can still say
the old TK numbers.

## What it handles

| Topic | Example customer line | What happens |
|---|---|---|
| Greeting | สวัสดีครับ | Welcome and menu |
| Outstanding balance | บิลเดือนนี้ต้องจ่ายเท่าไหร่ | Asks for the phone number, verifies with the last 4 ID digits, gives the amount and due date |
| Payment channels | จ่ายได้ที่ไหนบ้าง | Lists the channels |
| Order status | ของยังไม่มาเลย | Asks for the order number and gives the status, carrier and expected date. Past the expected date, offers a ticket to chase it |
| Cancel an order | ยกเลิกออเดอร์ | Not shipped yet: offers a cancellation request (ticket). Shipped: explains returns |
| Change delivery address | เปลี่ยนที่อยู่จัดส่ง | Hands over with the order number (an agent changes it) |
| Not received / wrong or damaged item | ขึ้นว่าส่งแล้วแต่ยังไม่ได้ของ, ได้ของผิด | Delivered: offers a ticket (check with the carrier / return or exchange) |
| Report a problem | เน็ตหลุดบ่อยตั้งแต่เมื่อวาน | Confirms the summary and opens a ticket |
| Case status | เรื่อง CS0001001 ถึงไหนแล้ว, ซีเอส 1001 | State and date of the case (no details without verification); Awaiting Info: offers the agent at once; open: offers an agent to speed it up |
| FAQ (from the `faq` table) | จ่ายแล้วแต่ยอดยังไม่ลด, ผ่อนได้ไหม, ขอใบเสร็จ, ลืมเลขบัตร | The stored answer, then nothing / a ticket offer / a handoff |
| Opening hours | เปิดกี่โมง | Gives the opening hours and whether agents are working now |
| Human agent | ขอคุยกับเจ้าหน้าที่ | Hands off at any point (`handoff: true`), with the order and ticket talked about. Outside `AGENT_HOURS`, offers a call back instead |
| Thanks / goodbye | ขอบคุณครับ, บายบาย | Polite close and session ends |

It also handles:
- **Thai input:** Thai digits, stretched letters (ครับบบ), polite particles, and numbers split
  with spaces or dashes.
- **Moving around:** "ยกเลิก" leaves the current step, and the customer can change topic mid-step.
- **Not understood:** after 2 misunderstood lines the bot offers a human agent. After 3 failed ID
  checks it hands off for account safety.
- **Proactive:** after the balance it asks aloud whether the customer wants the payment channels
  (so it works on the phone too) and says when the due date has passed; after a ticket it says how
  to follow it up ("เช็คเรื่อง CS0001001").
- **Tickets need a way back:** a customer who did not verify is asked for a number to call back.
- **Never changes an order itself:** cancellations, address changes and returns become a ticket or
  a handoff for a person.

## Layout

| Path | What it holds |
|---|---|
| `callcenter_bot/config.py` | Brand name, bot voice (ค่ะ/ครับ), hours, payment channels, menu, limits |
| `callcenter_bot/intents.py` | Keyword lists per topic. **Tune recognition here.** |
| `callcenter_bot/normalize.py` | Cleans up Thai input before matching |
| `callcenter_bot/bot.py` | Conversation engine: topics, steps, verification, handoff |
| `callcenter_bot/ai_fallback.py` | Optional AI answers (Claude) for what the rules don't cover |
| `callcenter_bot/db.py`, `data/*.sql` | The tables, demo rows, and checks for admin edits |
| `callcenter_bot/backend.py` | What the bot asks of the tables. Rewrite to use your real systems. |
| `channels/webchat/` | Web server (`server.py`), chat page (`static/index.html`), admin page (`static/admin.html`), and `static/runtime.js`, which runs the bot on the server or in the browser |
| `channels/audio_connector/` | Genesys Audio Connector voice bot: WebSocket server, Azure Thai speech, call logic, setup guide |
| `channels/genesys/` | Genesys Cloud Bot Connector (`connector.py`), bot registration (`bots.json`), setup guide |
| `channels/voice/` | Phase 2 plan |
| `tests/` | Unit and conversation tests |

## Adapting it to your company

1. **Your topics.** Add keywords in `intents.py`, then a `_on_<topic>` method in `bot.py`. Collect
   real chat logs and add the words customers actually use. This matters more than anything else.
2. **Your systems.** Rewrite the four functions in `backend.py` to call your CRM, billing, order
   and ticketing systems.
3. **Your wording.** Edit `config.py`, and the reply text in `bot.py`.
4. **Live agents.** In `channels/webchat/server.py`, at the `TODO` where `reply.handoff` is true,
   connect your agent desk (LINE OA, Zendesk, Freshchat, Genesys, ...).
5. **Optional AI fallback.** `Bot(fallback=fn)` calls `fn(message, session)` for lines no rule
   understood. Plug in an FAQ search or an LLM there, while the sensitive steps (identity checks,
   balances) stay rule-based.

## Before production

- Serve behind HTTPS (nginx, or a cloud load balancer). Add rate limiting.
- Sessions are kept in memory, so a restart forgets them and they work on one process only.
  Move them to Redis to run more than one server.
- The database is a single SQLite file. Back it up, and keep it off the public web root. For many
  agents or servers at once, move the tables to PostgreSQL or MySQL (same columns, same `db.py` calls).
- The admin password is HTTP Basic auth: serve over HTTPS only, and use a long password.
- PDPA: logs mask phone and ID numbers (`mask_digits`). Add a privacy notice to the chat page,
  and set a retention period for transcripts.
- Replace the identity check (last 4 ID digits) with whatever your security policy requires,
  such as an OTP by SMS.
