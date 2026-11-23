# Handoff: ทดสอบโทรเข้า Genesys จริง จาก MacBook

เอกสารนี้ใช้ส่งต่องาน: บอกว่าตอนนี้มีอะไรแล้ว, วิธีรัน voicebot บน MacBook แล้วโทรเข้า Genesys Cloud
จริงเพื่อทดสอบ, วิธีแก้เมื่อมีปัญหา และงานที่ยังเหลือ

```
มือถือ ─โทร─► เบอร์ Genesys ─► Inbound Call flow ─► Call Audio Connector
                                                        │ wss://xxxx.trycloudflare.com/audiohook
                                                        ▼
                     MacBook: tools/run_voicebot_demo.sh (cloudflared ─► บอท localhost:8080)
                                                        │ Azure Speech: ฟังไทย / พูดไทย
                                                        ▼
                     จบ: ส่ง intent + verifiedPhone ให้ Architect ─► Transfer to ACD ─► เจ้าหน้าที่
```

---

## 0. สถานะตอนนี้

| ส่วน | สถานะ |
|---|---|
| บอทภาษาไทย (ตรรกะ, ตารางข้อมูล, หน้าจัดการ `/admin`) | ใช้ได้ มีเทสต์ |
| เว็บแชท + โหมดโทรบนเว็บ (GitHub Pages) | ใช้ได้ |
| Voicebot ผ่าน Genesys Audio Connector + Azure | **เขียนเสร็จและเทสต์กับ Genesys จำลองแล้ว ยังไม่เคยลองกับ Genesys และ Azure จริง** |
| Genesys Bot Connector (แชท) | **ไม่ใช้ในงานนี้** งานนี้เชื่อม Genesys ผ่าน Audio Connector เท่านั้น (Genesys รองรับ Call Bot Connector เฉพาะ messaging flow ใช้กับสายโทรศัพท์ไม่ได้) |

**สิ่งที่การทดสอบรอบนี้ต้องยืนยัน**
1. Genesys เชื่อมต่อเข้ามาที่บอทได้ (โปรโตคอลและ API key)
2. Azure ฟังภาษาไทยในสายโทรศัพท์ได้แม่นพอ
3. ค่าที่บอทส่งกลับ (output variables) ไปถึง Architect และขึ้นให้เจ้าหน้าที่เห็น

---

## 1. สิ่งที่ต้องมี

- **MacBook:** macOS พร้อม [Homebrew](https://brew.sh)
- **Azure Speech:** Speech resource ใน region **Southeast Asia** พร้อม key ดูได้ที่ Azure portal → resource → Keys and Endpoint
- **ระบบโทรศัพท์ของ Genesys ต้องเป็น Genesys Cloud Voice หรือ BYOC Cloud:** Audio Connector
  **ใช้กับ BYOC Premises และ premises-based Edge (LDM) ไม่ได้** ให้ถามผู้ดูแล Genesys ก่อนเริ่ม
- **โควตา:** หนึ่ง org มี Audio Connector integration ได้ไม่เกิน 5 ตัว ถ้าเต็มแล้วให้ใช้ตัวที่มีอยู่แทนการสร้างใหม่
- **สิทธิ์ใน Genesys Cloud:**
  - ติดตั้งและตั้งค่า integration
  - แก้และ publish Architect flow
  - สร้างและ publish Script (ให้เจ้าหน้าที่เห็นข้อมูลจากบอท ข้อ 5.5)
  - ผูกเบอร์โทรเข้ากับ flow (call routing / DID)
  - มีคิวเจ้าหน้าที่และ agent หนึ่งคนสำหรับทดสอบการโอนสาย
- **Audio Connector ใน Genesys:** อาจต้องเปิดใช้หรือซื้อเพิ่ม (คิดค่าใช้จ่ายรายนาที) ให้เช็คกับผู้ดูแล Genesys

---

## 2. เตรียมเครื่อง Mac (ทำครั้งเดียว)

```bash
brew install python@3.12 cloudflared git
```

```bash
git clone https://github.com/gcat332/cc_ai_chat_hybrid_bot.git
cd cc_ai_chat_hybrid_bot
```

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-voice.txt
```

ตรวจว่าทุกอย่างพร้อม (ไม่ต้องใช้ Azure หรือ Genesys) ควรได้ `OK`:

```bash
.venv/bin/python -m unittest discover -s tests
```

ถ้าเคย clone ไว้แล้ว ให้อัปเดตด้วย `git pull origin main`

---

## 3. ใส่ key

```bash
cp voicebot.env.example voicebot.env
openssl rand -hex 32          # คัดลอกผลลัพธ์ไปใส่เป็น AUDIO_CONNECTOR_API_KEY
open -e voicebot.env          # เปิดแก้ใน TextEdit
```

ใส่ค่าในไฟล์:

```
AUDIO_CONNECTOR_API_KEY=<ค่าที่สุ่มได้>
AZURE_SPEECH_KEY=<key จาก Azure>
AZURE_SPEECH_REGION=southeastasia
```

`voicebot.env` ถูกตั้งไว้ไม่ให้ขึ้น git อยู่แล้ว ห้ามส่ง key ทางแชทหรืออีเมล

---

## 4. เปิดบอทให้ Genesys เรียกถึง

**ลองแบบไม่ใช้ Azure ก่อน** เพื่อเช็คว่า tunnel ทำงาน:

```bash
FAKE_SPEECH=1 tools/run_voicebot_demo.sh
```

จะได้ผลประมาณนี้:

```
Base Connection URI:  wss://xxxx-xxxx.trycloudflare.com/audiohook
Health check: https://xxxx-xxxx.trycloudflare.com/   (should say OK)
```

เปิดลิงก์ Health check ในเบราว์เซอร์ ถ้าขึ้น `OK` แปลว่าคนภายนอกเรียกถึงบอทได้แล้ว กด Ctrl+C เพื่อปิด

**รันจริง (ใช้ Azure):**

```bash
caffeinate -dims tools/run_voicebot_demo.sh
```

- `caffeinate` กันไม่ให้ Mac หลับระหว่างทดสอบ ถ้า Mac หลับ สายจะหลุด
- เปิดหน้าต่าง Terminal นี้ไว้ตลอด log ของทุกสายจะขึ้นที่นี่
- **ที่อยู่ `wss://` เปลี่ยนทุกครั้งที่รันใหม่** ต้องไปอัปเดตใน Genesys ทุกครั้ง (ข้อ 5.2)

---

## 5. ตั้งค่า Genesys Cloud

ชื่อเมนูอาจต่างไปตามรุ่น UI ของ Genesys

### 5.1 ติดตั้ง Audio Connector

Admin → Integrations → **+ Integrations** → ค้นหา **Audio Connector** → Install → ตั้งชื่อ เช่น
`Thai Voicebot (Mac test)`

### 5.2 ตั้งค่า integration

- **Configuration → Properties → Base Connection URI:** `wss://xxxx-xxxx.trycloudflare.com/audiohook`
  ใช้ค่าจากข้อ 4
- **Configuration → Credentials:**
  - **API Key** = ค่า `AUDIO_CONNECTOR_API_KEY` ใน `voicebot.env`
  - ถ้ามีช่อง **Client Secret** ให้สุ่มค่าด้วย `openssl rand -hex 32` แล้ว**จดไว้ใน `voicebot.env`**
    เป็น `AUDIO_CONNECTOR_CLIENT_SECRET=...` ตอนนี้บอทยังไม่ได้ตรวจลายเซ็นคำขอ แต่เมื่อเพิ่มการตรวจ
    (ข้อ 9) ต้องใช้ค่าเดียวกันทั้งสองฝั่ง
- Save แล้วเปลี่ยนสถานะเป็น **Active**

### 5.3 สร้าง Inbound Call flow (Architect)

1. Architect → Inbound Call → สร้าง flow ใหม่ เช่น `Thai Voicebot Test`
2. ตั้ง **Supported language = Thai (th-TH)** ถ้า org ยังไม่ได้เปิดภาษาไทยจนตั้งหรือ publish ไม่ได้
   ใช้ภาษาที่มีอยู่ไปก่อนได้ เพราะบอทฟังและพูดเองผ่าน Azure ทั้งหมด (ยังไม่ได้ลองกับ org จริง)
3. ใน Initial State ใส่ action **Call Audio Connector**:
   - **Integration:** ตัวที่สร้างในข้อ 5.1
   - **Connector ID:** อะไรก็ได้ เช่น `thai-bot`
   - **Output variables:** สร้างตัวแปรรับค่า (เป็น String ทั้งหมด)

     | output | ตัวแปรใน flow | ค่าที่เป็นไปได้ |
     |---|---|---|
     | `intent` | `Flow.intent` | `live-agent-handoff`, `end-conversation`, `no-response`, `caller-hung-up` |
     | `handoffReason` | `Flow.handoffReason` | `agent`, `verify_failed`, `speech_error`, `adapter_error` |
     | `verifiedPhone` | `Flow.verifiedPhone` | เบอร์ที่ยืนยันตัวตนผ่านแล้ว หรือว่าง |
     | `ticket` | `Flow.ticket` | เช่น `CS0001001` |
     | `topics` | `Flow.topics` | เช่น `check_balance,report_problem` |
     | `lastCustomerText` | `Flow.lastCustomerText` | ประโยคล่าสุดของลูกค้า (ตัวเลขถูกปิดบัง) |

4. ทาง **Success** ของ action ใส่ **Switch** ตาม `Flow.intent`:
   - `live-agent-handoff` → **Set Participant Data** (`verifiedPhone`, `ticket`, `topics`,
     `lastCustomerText`) → **Set Screen Pop** (Script จากข้อ 5.5) → **Transfer to ACD** (คิวทดสอบ)
   - `end-conversation` / `no-response` → **Disconnect**
   - อื่น ๆ → **Disconnect**
5. ทาง **Failure** (เช่น บอทไม่ได้เปิดอยู่ หรือ key ผิด) → **Transfer to ACD** ลูกค้าจะได้ไม่หลุดสาย
6. Save → **Publish**

### 5.4 ผูกเบอร์โทรเข้ากับ flow

ผูกเบอร์ทดสอบ (DID) เข้ากับ flow `Thai Voicebot Test` ที่ Admin → Telephony / **Call Routing**
แนะนำให้ใช้เบอร์ที่ไม่ใช่เบอร์ลูกค้าจริง

### 5.5 ให้เจ้าหน้าที่เห็นข้อมูลจากบอท (Script)

Set Participant Data อย่างเดียว**ไม่ทำให้ข้อมูลขึ้นบนหน้าจอเจ้าหน้าที่** ต้องมี Script ที่แสดงค่า:

1. Admin → Contact Center → **Scripts** → สร้าง Script ใหม่ เช่น `Thai Voicebot Handoff`
2. เพิ่ม variable แบบ **Input** ชื่อตรงกับ participant data: `verifiedPhone`, `ticket`, `topics`,
   `lastCustomerText` (ตัวพิมพ์ใหญ่เล็กต้องตรง)
3. วางข้อความหรือ text component แสดงตัวแปรทั้ง 4 ในหน้า Script → Save → **Publish**
4. ใน flow ข้อ 5.3 ใส่ **Set Screen Pop** เลือก Script นี้ ก่อน Transfer to ACD แล้ว publish flow ใหม่

ชื่อเมนูอาจต่างไปตามรุ่น UI และสิทธิ์ ให้ยืนยันขั้นตอนกับผู้ดูแล Genesys

---

## 6. สคริปต์ทดสอบการโทร

โทรจากมือถือเข้าเบอร์ทดสอบ ดู log ใน Terminal ไปพร้อมกัน

ข้อมูลตัวอย่างในฐานข้อมูล (ยืนยันตัวตนด้วยเลขบัตรประชาชน 13 หลัก):

| เลขบัตรประชาชน | ลูกค้า | มีอะไร |
|---|---|---|
| `3294367792962` | นางสาวพลอยใส ใจดี (0815493626) | สินเชื่อบ้าน, บัตร Platinum, ออมทรัพย์, เคส CS0001001 |
| `1101700123456` | นายสมชาย ใจงาม (0812345678) | สินเชื่อส่วนบุคคล, บัตร Signature |
| `1509900543215` | นายทดสอบ ระบบ (0636538939) | บัตร Classic ยอดค้าง 520.75 บาท |

| # | ทำ | สิ่งที่ควรได้ | ✓ |
|---|---|---|---|
| 1 | โทรเข้า | "สวัสดีครับ ผู้ช่วยอัตโนมัติ ต้องการติดต่อเรื่องใดครับ" | |
| 2 | พูด "ต้องการปิดบัญชีสินเชื่อบ้าน" | "ต้องการปิดบัญชีสินเชื่อบ้าน ใช่ไหมครับ" | |
| 3 | พูด "ใช่" | "ต้องการปิดบัญชีเลย หรือสอบถามรายละเอียดก่อนครับ" | |
| 4 | พูด "ขอทราบรายละเอียดก่อน" | "ปิดเพื่อย้ายไปธนาคารอื่น หรือปิดยอดเองครับ" | |
| 4.1 | พูด "จะรีไฟแนนซ์ไปกสิกร" | "เข้าใจครับ ขอเลขบัตรประชาชน 13 หลัก เพื่อยืนยันตัวตนครับ" | |
| 5 | กด `3294367792962#` บนแป้น หรือพูดทีละตัว | "ขอบคุณครับคุณพลอยใส ผมจะโอนให้เจ้าหน้าที่ตรวจสอบสินเชื่อ ..." แล้วสายเข้าคิว | |
| 6 | ฝั่ง agent | เห็น `customerName=นางสาวพลอยใส ใจดี`, `requestDetail=ปิดบัญชีสินเชื่อบ้านเพื่อรีไฟแนนซ์ (สอบถามรายละเอียดก่อน)`, `closeReason=รีไฟแนนซ์ไปธนาคารอื่น (กสิกรไทย)`, `loanDetail=สินเชื่อบ้าน ลงท้าย 4567 ...`, `handoffReason=loan_refinance` | |
| 7 | โทรใหม่ พูด "ยอดค้างชำระ" แล้วกด `1509900543215#` | "บัตร Classic ลงท้าย 2222 ยอดค้าง 520 บาท 75 สตางค์ ..." | |
| 8 | พูดแทรกระหว่างที่บอทพูด | บอทหยุดพูดทันทีแล้วฟัง | |
| 9 | พูด "บัตรเครดิตหาย" (ไม่ต้องยืนยันซ้ำถ้ายืนยันไปแล้ว) | โอนเจ้าหน้าที่ทันทีเพื่อระงับบัตร (`card_lost`) | |
| 10 | โทรใหม่แล้วเงียบ | ประมาณ 8 วินาทีถาม "ยังอยู่ในสายไหมครับ" แล้วจึงวางสาย | |

**จดผลไว้ส่งกลับ:** ประโยคที่ Azure ฟังผิด (ดูได้ใน log บรรทัด `in='...'`), ความหน่วงที่รู้สึก
และเสียงที่ฟังไม่เป็นธรรมชาติ

ความหน่วงรอบนี้**ยังไม่ใช่ตัวเลขจริง** เสียงวิ่ง Genesys → Cloudflare → Mac → Azure ส่วน Genesys
แนะนำให้วางเซิร์ฟเวอร์ใกล้ region ของ org ให้วัดใหม่หลังย้ายไปเซิร์ฟเวอร์ถาวร

---

## 7. แก้ปัญหา

| อาการ | ดูที่ | สาเหตุ / วิธีแก้ |
|---|---|---|
| โทรแล้วเข้าทาง Failure ทันที ไม่มีอะไรใน log | Terminal | ที่อยู่ใน Genesys เก่า เพราะรันสคริปต์ใหม่แล้วที่อยู่เปลี่ยน หรือ Mac หลับ ให้อัปเดต Base Connection URI |
| log: `refused a connection: wrong or missing x-api-key` | Terminal | API Key ใน Genesys ไม่ตรงกับ `voicebot.env` |
| log: `refused a connection to /...` | Terminal | URI ต้องลงท้ายด้วย `/audiohook` |
| log: `probe connection answered` แต่ไม่มีสายจริง | Terminal | ปกติ Genesys ทดสอบการเชื่อมต่อ ให้โทรจริงอีกครั้ง |
| สายถูกโอนเข้าคิวทันทีโดยไม่มีคำทักทาย / log: `text-to-speech failed, handing over` หรือ `speech recognition error` | Terminal | Azure ใช้ไม่ได้: `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` ผิด หรือ resource ไม่ได้อยู่ region นั้น บอทจะโอนให้เจ้าหน้าที่ (`handoffReason=speech_error`) |
| ทักทายแล้วไม่ตอบอะไร | log บรรทัด `in=` | Azure ไม่ได้ยินเสียง หรือไม่เคยเห็นบรรทัด `in=` เลย ให้ดูว่า Genesys ส่งเสียงมาไหม แล้วส่ง log มา |
| โอนสายแล้วเจ้าหน้าที่ไม่เห็นข้อมูล | Architect, Script | ชื่อ output variable ต้องตรงตัวพิมพ์ใหญ่เล็ก ต้องมี Set Participant Data และ Set Screen Pop ก่อน Transfer to ACD และ Script ต้อง publish แล้ว (ข้อ 5.5) |
| สายเงียบหรือหลุดกลางสาย / log: `connection ended` | Terminal | Wi-Fi หลุด, tunnel ล่ม หรือ Mac หลับ Audio Connector **ต่อสายเดิมกลับไม่ได้** สายนั้นจบเลย ให้โทรใหม่ |
| Genesys ไม่รับคำตอบ (error ใน Architect debugger) | Architect | อาจเป็นชื่อฟิลด์โปรโตคอลไม่ตรง (ข้อ 9) ให้ส่ง error มา |

ดู log ย้อนหลัง: เลื่อนขึ้นใน Terminal เบอร์และเลขบัตรใน log ถูกปิดบังแล้ว

---

## 8. ไฟล์สำคัญ

| ไฟล์ | หน้าที่ |
|---|---|
| `tools/run_voicebot_demo.sh` | เปิดบอท + tunnel แล้วพิมพ์ที่อยู่ `wss://` |
| `voicebot.env` | key ต่าง ๆ (ไม่ขึ้น git) |
| `channels/audio_connector/call.py` | ตรรกะในสาย: ทักทาย, พูดแทรก, กดเลข, เงียบ, วางสาย, ค่าส่งกลับ |
| `channels/audio_connector/speech.py` | Azure ฟังและพูดไทย (เสียง, ความเร็ว, คำที่ช่วยให้ฟังแม่น) |
| `channels/audio_connector/protocol.py` | ข้อความโปรโตคอล Audio Connector |
| `channels/audio_connector/README.md` | คู่มือฉบับเต็ม (deploy บนเซิร์ฟเวอร์, Caddy, TLS) |
| `callcenter_bot/bot.py` | คำตอบของบอท แก้ข้อความที่นี่ |
| `callcenter_bot/data/seed.sql` | ข้อมูลตัวอย่าง |

ปรับเสียงได้ใน `voicebot.env`:
- `AZURE_SPEECH_VOICE=th-TH-NiwatNeural` (เสียงผู้ชาย)
- `AZURE_SPEECH_RATE=-10%` (ช้าลง)
- `AZURE_SPEECH_END_SILENCE_MS=1000` (รอนานขึ้นก่อนตัดประโยค)

---

## 9. ยังไม่ได้ยืนยัน / งานที่เหลือ

- [ ] **ชื่อฟิลด์ของโปรโตคอล:** เทียบกับโค้ดตัวอย่าง AudioHook ของ Genesys
  ([purecloudlabs/audiohook-reference-implementation](https://github.com/purecloudlabs/audiohook-reference-implementation),
  `app/audiohook/src/protocol/`) แล้ว
  - **ตรงกัน:** ชื่อข้อความ (`open`/`opened`, `ping`/`pong`, `close`/`closed`, `disconnect`,
    `paused`/`resumed`, `event`), ข้อมูลตอนเปิดสาย (`conversationId`, `participant`, `media`), เสียง
    PCMU 8000 Hz, `startPaused` และ `disconnect.reason` = `completed` / `unauthorized` / `error`
  - **ยังยืนยันไม่ได้** (เป็นส่วนเฉพาะของ Audio Connector ไม่มีในโค้ดตัวอย่าง): `outputVariables`
    ใน `disconnect`/`closed`, ข้อความ `dtmf` และ event `barge_in` ดูในการโทรทดสอบข้อ 3, 5, 8
  - หน้า developer.genesys.cloud ดึงอ่านอัตโนมัติไม่ได้ เพราะเป็นหน้าเว็บที่โหลดเนื้อหาด้วย JavaScript ให้เปิดในเบราว์เซอร์
    ถ้าการทดสอบมีปัญหา: https://developer.genesys.cloud/devapps/audiohook
- [ ] **ลายเซ็นคำขอของ Genesys (Client Secret):** ยังไม่ได้ตรวจ ตอนนี้ตรวจแค่ API key ต้องทำก่อนขึ้น production
- [ ] **ที่อยู่ถาวร:** ย้ายจาก tunnel ชั่วคราวไปเซิร์ฟเวอร์ AgentHub ที่มี Caddy อยู่แล้ว (ดู README หัวข้อ C. Caddy)
  หรือใช้ Cloudflare named tunnel
- [ ] **ข้อมูลจริง:** เชื่อม `callcenter_bot/backend.py` เข้ากับระบบลูกค้าจริงแทนตารางตัวอย่าง
- [ ] **ค่าใช้จ่าย:** ดูค่า Audio Connector (รายนาที) และค่า Azure ต่อสายจากผลการทดสอบ
- [ ] (ถ้าต้องการ) ตัวจำลองสายบน Mac ที่คุยผ่านไมค์ได้โดยไม่ต้องผ่าน Genesys
