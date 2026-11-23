# Phase 2: phone line (plan)

Voice **in the web chat** already works (🎤 button, browser speech, see the main README). This
plan is for customers who **call a phone number**. That needs a telephony provider and
server-side speech services, because there is no browser on a phone call.

The bot core (`callcenter_bot`) is already independent of the channel. The voice line is a
second adapter next to `channels/webchat`, and it calls the same `Bot.reply(session_id, text)`.

```
caller ──► phone system (SIP / Twilio / Amazon Connect / Genesys)
             │ audio
             ▼
        Thai speech-to-text  ──text──►  Bot.reply(call_id, text)  ──Reply──►  Thai text-to-speech
                                                                                 │ audio
                                              Reply.handoff = True  ──► transfer call to agent queue
```

## What the adapter does with a Reply

| Reply field | Web chat | Voice |
|---|---|---|
| `text` | show the bubble | send to text-to-speech |
| `quick_replies` | buttons | read as a menu ("กด 1 เช็คยอด กด 2 ...") or keep as words the caller can say |
| `handoff` | open a live-agent chat | transfer the call to the agent queue |
| `end` | close the session | say goodbye and hang up |

## Things to change for voice

1. **Numbers by keypad (DTMF).** Phone numbers and the 4 ID digits are best entered on the keypad.
   Speech-to-text often mishears digits. The steps already accept plain digit strings, so feed
   DTMF digits in as the message text.
2. **Spoken digits.** Done: `normalize.spoken_digits` turns "ศูนย์แปดหนึ่ง..." into digits.
3. **Shorter replies.** Lists (payment channels) should be shorter when spoken. Add a `speech`
   variant to `Reply` where the written text is too long to listen to.
4. **Silence and barge-in.** Re-prompt after about 5 seconds of silence and let the caller interrupt
   the bot. Most phone platforms handle this.
5. **Thai speech services to compare:** Google Cloud Speech-to-Text and Text-to-Speech (th-TH),
   Azure Speech (th-TH, e.g. the Premwadee/Niwat voices), Amazon Transcribe and Polly. Also
   local Thai providers. Test them with real call recordings, since accuracy on phone audio
   (8 kHz) varies a lot between providers.
6. **Recording consent (PDPA).** Play a notice before recording, and mask numbers in transcripts
   the same way `channels/webchat/server.py` masks its logs.
