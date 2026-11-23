# Genesys Audio Connector: the Thai voice bot on a real phone line

Callers talk to the bot in Thai on a Genesys Cloud phone line, the way the web page's call mode
works: no menus, no buttons. When they need a person, the call goes to an agent queue with what
the bot learned.

```
caller ─► Genesys Cloud Voice ─► Inbound Call flow ─► Call Audio Connector ─► wss://YOUR-SERVER/audiohook
                                                         ⇅ call audio (PCMU 8 kHz)
                                     this server: Azure speech-to-text (th-TH) ─► bot + tables ─► Azure voice (th-TH)
                                                         │ disconnect + outputVariables
          Agent ◄─ Transfer to ACD ◄─ Set Participant Data ◄─ Architect reads intent, verifiedPhone, ticket...
```

| On the call | How |
|---|---|
| Talk freely in Thai | Azure speech recognition (th-TH), streaming |
| Thai voice, the same on every phone | Azure neural voice, `th-TH-PremwadeeNeural` by default |
| Interrupt the bot | Caller speech stops the bot's audio at once (barge-in) |
| Numbers by voice or keypad | Spoken digits, or keypad digits ended by `#` (or a 2.5 s pause) |
| Silence | "ยังอยู่ในสายไหมคะ", then a polite goodbye |
| Hand over to a person | Ends with `intent = live-agent-handoff` plus the verified phone, for Architect to route |

## 1. Azure Speech

1. In the Azure portal, create a **Speech** resource. Choose region **Southeast Asia**, which is
   close to Thailand.
2. From **Keys and Endpoint**, copy a key and the region.

## 2. Run it on the server

Needs Python 3.10 or newer.

```bash
git clone https://github.com/gcat332/cc_ai_chat_hybrid_bot.git && cd cc_ai_chat_hybrid_bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-voice.txt
```

Create `/etc/thai-voicebot.env` (readable by root only, never committed):

```bash
AUDIO_CONNECTOR_API_KEY=<long random string, also entered in Genesys>
AZURE_SPEECH_KEY=<Azure key>
AZURE_SPEECH_REGION=southeastasia
# optional
AZURE_SPEECH_VOICE=th-TH-PremwadeeNeural     # or th-TH-NiwatNeural (male), th-TH-AcharaNeural
AZURE_SPEECH_RATE=0%                         # -10% slower, +10% faster
CALLCENTER_DB=/var/lib/thai-voicebot/callcenter.db   # share it with the web chat/admin to edit the same rows
PORT=8080
```

To make a random API key: `openssl rand -hex 32`

Try it in the foreground first:

```bash
set -a; . /etc/thai-voicebot.env; set +a
python -m channels.audio_connector.server
# Audio Connector on ws://0.0.0.0:8080/audiohook
```

Then keep it running with systemd, in `/etc/systemd/system/thai-voicebot.service`:

```ini
[Unit]
Description=Thai voice bot (Genesys Audio Connector)
After=network-online.target

[Service]
WorkingDirectory=/opt/cc_ai_chat_hybrid_bot
EnvironmentFile=/etc/thai-voicebot.env
ExecStart=/opt/cc_ai_chat_hybrid_bot/.venv/bin/python -m channels.audio_connector.server
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now thai-voicebot
```

### Public wss:// (TLS)

Genesys only connects to a public **wss://** address with a valid certificate. If the server
already runs nginx with HTTPS (as for AgentHub), add:

```nginx
location /audiohook {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;      # a call can last long
    proxy_send_timeout 3600s;
}
```

Check from outside: `curl https://YOUR-DOMAIN/audiohook` should answer `Invalid API key`.

## 3. Genesys Cloud

1. **Install the integration:** Admin → Integrations → install **Audio Connector** from AppFoundry.
   Audio Connector works with Genesys Cloud Voice and BYOC Cloud, but not BYOC Premises.
2. **Configure it:**
   - **Base Connection URI:** `wss://YOUR-DOMAIN/audiohook`
   - **Credentials:** API Key = `AUDIO_CONNECTOR_API_KEY`
   - Activate it.
3. **Build an Inbound Call flow** in Architect:

   1. Set the flow language to **Thai**.
   2. Add **Call Audio Connector**: choose the integration. For **Connector ID**, enter any name,
      e.g. `thai-bot`. The server accepts `/audiohook/<anything>`.
   3. Map the **output variables** to flow variables (all strings):

      | Output | Values |
      |---|---|
      | `intent` | `live-agent-handoff`, `end-conversation`, `no-response`, `caller-hung-up` |
      | `handoffReason` | `agent` (asked for a person), `verify_failed`, `speech_error`, `adapter_error` |
      | `verifiedPhone` | phone number that passed the ID check, or empty |
      | `ticket` | e.g. `TK1001` when a problem was reported |
      | `topics` | e.g. `check_balance,report_problem` |
      | `lastCustomerText` | the caller's last words (numbers masked) |
      | `ani`, `turns` | caller number, number of turns |

   4. After the action:
      - `intent == "live-agent-handoff"` → **Set Participant Data** (`verifiedPhone`, `ticket`,
        `topics`, `lastCustomerText`) → **Set Screen Pop** if you use scripts → **Transfer to ACD**.
      - `end-conversation` or `no-response` → **Disconnect**.
      - **Failure** path (server down, wrong key) → **Transfer to ACD**, so no caller is dropped.

4. Call the number and talk in Thai. To test the balance check, use phone `0636538939` and
   ID last 4 digits `8939`.

## Try it without Genesys or Azure

The tests play whole calls the way Genesys does: greeting, balance check by voice and keypad,
interruption, silence, handover data, probe, ping, stereo audio and the API key. They use fake
speech, so they need no Azure key:

```bash
python -m unittest tests.test_audio_connector -v
```

`python -m channels.audio_connector.server --fake-speech` runs the server without Azure. Callers
then "speak" with frames that start with `SAY:`, so it is for tests only.

## Notes and limits

- **Not yet tried on a real Genesys organization or with real Azure.** Message names follow the
  public AudioHook protocol as used by Pipecat and Genesys' own sample connector. Genesys'
  developer pages could not be reached while this was built. On the first real call, watch the
  server log (`journalctl -u thai-voicebot -f`) and the Architect debugger.
- **Genesys request signatures are not checked yet.** Genesys can also sign requests with the
  integration's client secret; this server only checks the API key. Add signature checking before
  production.
- **Costs per minute:** Genesys bills Audio Connector streaming per minute (BYOT), and Azure
  bills speech recognition and voice per use. Check current prices for your contracts.
- **Capacity:** each call holds one WebSocket and one Azure recognition stream. One small server
  handles dozens of calls, because the bot itself is light.
- **Privacy (PDPA):** caller audio goes to Azure (choose the Southeast Asia region). Logs mask
  phone and ID numbers. Tell callers the call is handled by an automated assistant; the greeting
  does.
