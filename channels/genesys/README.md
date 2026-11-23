# Genesys Cloud Bot Connector

Genesys Cloud runs the call or chat: telephony, speech recognition, text-to-speech, queues and
agents. This bot decides what to say. Each customer turn, Genesys sends the customer's words to
this server and plays or shows the reply.

```
customer ─► Genesys Cloud ─► Architect flow ─► "Call Bot Connector" ─► POST /api/genesys/botconnector
                                                                    ◄─ reply + botState + intent
```

The code is in `connector.py`. The bot core, tables and admin page are the same ones the web chat
uses.

## Before you start: check these in your Genesys organization

1. **Voice or chat?** Every public Bot Connector example we found uses an **Inbound Message**
   flow (chat/messaging). Open an **Inbound Call** flow in Architect and search the toolbox for
   **Call Bot Connector**:
   - If it is there, this connector also works for phone calls.
   - If not, use it for chat. For phone calls, use Audio Connector instead (option B), which is
     more work.
2. **Licence:** the Genesys Bot Connector integration may need an add-on (e.g. a "bring your own
   technology" bundle). Ask your Genesys administrator or account manager.
3. **Thai speech:** Genesys lists Thai (th-TH), but notes that support is limited, and its Thai
   text-to-speech voices are changing. Test a Thai prompt and Thai speech recognition in your org
   before going further.

## 1. Run the bot where Genesys can reach it

Genesys must reach the server over public **HTTPS**, e.g. Cloud Run, App Service, or a VPS
behind nginx. GitHub Pages cannot do this.

```bash
export GENESYS_SECRET='a-long-random-secret'      # Genesys sends this with every request
export ADMIN_PASSWORD='another-secret'             # for /admin (optional)
python -m channels.webchat.server --host 0.0.0.0 --port 8000
```

The server prints `Genesys Bot Connector on .../api/genesys/botconnector`. Without
`GENESYS_SECRET`, the connector answers 503 and does nothing.

| Setting | Default | What it does |
|---|---|---|
| `GENESYS_SECRET` | (none: connector off) | Secret Genesys must send |
| `GENESYS_SECRET_HEADER` | `x-bot-secret` | Header name it arrives in (a `Bearer ` prefix is accepted) |
| `GENESYS_REPLY_FORMAT` | `speech` | `speech`: numbers worded for text-to-speech (phone). `text`: as written (chat) |

A flow can also choose per conversation: set the bot input parameter `replyFormat` to `text`
for chat flows.

## 2. Create the integration in Genesys

1. **Admin → Integrations → Add integration → Genesys Bot Connector → Install.** Name it, e.g.
   `Thai Call Center Bot`.
2. **Configuration → Properties → Bot Connector Handle Utterance URI:**
   `https://YOUR-SERVER/api/genesys/botconnector`
3. **Configuration → Credentials → Configure → Add credential field:** name `x-bot-secret`,
   value = your `GENESYS_SECRET`. Save.
4. Copy the **integration ID** from the Details tab.

## 3. Register the bot (one time)

In Genesys **Developer Center → API Explorer**, run
`PUT /api/v2/integrations/botconnector/{integrationId}/bots` with the contents of
[`bots.json`](bots.json) as the body. Then check it with the matching `GET`.

`PUT` replaces the whole bot list of that integration, so use a dedicated integration. The bot
declares these intents for Architect:

| Intent | When | Slots (outputs) |
|---|---|---|
| `continue` | normal turn (`botState: MOREDATA`), Genesys keeps the conversation going | `expectsDigits`: `"true"` while waiting for a phone, ID or order number |
| `live-agent-handoff` | customer asked for a person, failed the ID check 3 times, or the bot hit an error (`COMPLETE`) | `handoffReason` (`agent`, `verify_failed`, `adapter_error`), `verifiedPhone` |
| `end-conversation` | customer said goodbye (`COMPLETE`) | `verifiedPhone` |

## 4. Build the Architect flow

1. Add **Call Bot Connector**, choose the integration, the bot **Thai Call Center Bot** and
   version **1**. Leave the first input empty: the bot then greets the customer.
2. After it:
   - `live-agent-handoff` → **Transfer to ACD** (your queue). Pass `verifiedPhone` to the agent,
     e.g. as a participant attribute, so the agent sees who was verified.
   - `end-conversation` → **Disconnect**.
   - **Failure** path → apologise, then **Transfer to ACD**.
3. Set the flow language to **Thai (th-TH)** and choose a Thai voice, so Genesys recognises Thai
   and reads the replies in Thai.

## What the bot sends back

```json
{
  "replymessages": [{"type": "Text", "text": "คุณทดสอบ มียอดค้างชำระ 520 บาท 75 สตางค์ ..."}],
  "botState": "MOREDATA",
  "intent": "continue",
  "confidence": 1.0,
  "parameters": {"expectsDigits": "false"}
}
```

- **Errors:** never sent as HTTP errors. Genesys treats a non-200 as a hard failure that can drop
  the customer. A bot error returns `COMPLETE` + `live-agent-handoff` with a Thai apology.
- **Logs:** phone and ID numbers are masked.
- **Separate conversations:** each Genesys `botSessionId` is its own conversation.

## Test without Genesys

`tests/test_genesys.py` plays a whole call the way Genesys sends it: greeting, balance check
for the test number `0636538939` with the number spoken as Thai words, and handoff. Run:

```bash
python -m unittest tests.test_genesys
```

Or call the endpoint yourself:

```bash
curl -s -X POST http://localhost:8000/api/genesys/botconnector \
  -H 'Content-Type: application/json' -H "x-bot-secret: $GENESYS_SECRET" \
  -d '{"botId":"d150eb60-f36e-4f4c-850d-9eb679cb5258","botVersion":"1","botSessionId":"test-1",
       "inputMessage":{"type":"Text","text":"เช็คยอดค้างชำระ"},"languageCode":"th-th",
       "botSessionTimeout":3600,"genesysConversationId":"c-1"}'
```

## Not verified yet

The request and response fields follow Google's and other public Bot Connector adapters. This
connector has not been run against a real Genesys organization yet, and Genesys' own developer
pages could not be reached while building it. On the first real test, check the Architect
debugger. If Genesys rejects the reply, compare the field names with the "Bot Connector Customer
API" page in the Genesys Developer Center. Some adapters write `replyMessages` and
`MoreData`/`Complete` instead.
