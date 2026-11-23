# บอทไทยบนสายโทรศัพท์ผ่าน Genesys voice bot flow + Data Action

Genesys รับสาย ฟังภาษาไทยและพูดภาษาไทยเอง ทุกครั้งที่ผู้โทรพูด bot flow ส่ง**ข้อความ**ที่ Genesys
ถอดได้มาที่เซิร์ฟเวอร์เราผ่าน Data Action บอทตัวเดิม (`bot.py`, กฎภาษาไทย, ตาราง) ตอบกลับเป็นข้อความ
แล้ว Genesys อ่านออกเสียง ไม่ต้องใช้ Azure, Audio Connector หรือ `wss://`

```
ผู้โทร ─► Inbound Call flow ─► Call Bot Flow ─────────────────────────────────────────────┐
                                  │ วนทุกประโยค:                                          │
                                  │  1. Call Data Action ─► POST https://เรา/api/genesys/turn │
                                  │        {sessionId, text}  ◄─ {reply, action, ...}       │
                                  │  2. action = continue: Genesys พูด reply แล้วฟังประโยคถัดไป │
                                  │  3. action = handoff / end: ออกจาก bot flow พร้อม outputs   │
                                  ▼                                                        │
               Set Participant Data ─► Set Screen Pop ─► Transfer to ACD ─► เจ้าหน้าที่  ◄─────┘
```

**ค่าใช้จ่าย (Genesys Cloud CX 4):** voice bot flow ใช้ AI token 1 token ต่อ 17 นาที ($1/token) TTS รวมใน
ค่า bot flow แล้ว CX 4 ได้ token รายเดือนตามจำนวน agent (30 ต่อ named agent) ให้ผู้ดูแลเช็คว่าเหลือเท่าไหร่
หลังหักฟีเจอร์อื่นที่ใช้ token ก้อนเดียวกัน (เช่น Agent Copilot)

---

## ⚠️ ยังไม่ได้ยืนยัน: ทำ "ข้อ 0" ก่อนสร้างทั้งหมด

ทั้งระบบขึ้นกับว่า **voice bot flow ให้ข้อความดิบที่ผู้โทรพูดได้หรือไม่** เอกสารทางการของ Genesys ไม่ได้เขียนไว้ตรง ๆ
ข้อมูลที่มีมาจากชุมชนผู้ใช้ Genesys และภาษาไทยใน bot flow เป็นแบบ "partial NLU" ("Support for Thai is limited")

### 0. ทดลองดึงข้อความ (ประมาณ 30 นาที ไม่ต้องมีเซิร์ฟเวอร์)

สร้าง voice bot flow ทดลองภาษาไทย ผูกกับเบอร์ทดสอบ แล้วลองวิธีดึงข้อความทีละวิธี จนกว่าจะได้วิธีที่ใช้ได้:

| วิธี | ทำอย่างไร | ที่มา |
|---|---|---|
| **A. RegEx slot** | สร้าง slot type แบบ **RegEx** pattern `.+` แล้วใช้ **Ask for Slot** เก็บค่า | คำแนะนำในชุมชน |
| **B. `Session.LastCollectionUtterance`** | ใช้ **Ask for Intent** (มี intent ไหนก็ได้ 1 ตัว) แล้วอ่านตัวแปรนี้ ทั้งทาง match และ No Match | ผู้ใช้ในชุมชนรายงานว่าใช้ได้ ให้ค้นชื่อนี้ใน expression editor ก่อน |
| **C. AI-powered free-form slot** | Ask for Slot กับ slot type แบบ AI-powered → **Free-form** (เก็บได้ถึง 500 ตัวอักษร) | เอกสาร Genesys ผูกกับ Virtual Agent (0.5 token ต่อการโทร) |

แต่ละวิธีให้ทดสอบโดย**พูดอ่านค่าใส่ Communicate** ("ได้ยินว่า {{ค่าที่ได้}}") แล้วโทรพูด 4 ประโยคนี้:
"เช็คยอดค้างชำระ", "ศูนย์ หก สาม หก ห้า สาม แปด เก้า สาม เก้า", "ติดตามพัสดุ", "ขอคุยกับเจ้าหน้าที่"

จดไว้ว่า: วิธีไหนได้ข้อความ, Genesys ถอดภาษาไทยถูกแค่ไหน, ตัวเลขออกมาเป็นเลขอารบิก ("0636538939") หรือคำไทย
(บอทรับได้ทั้งสองแบบ) ถ้า**ไม่มีวิธีไหนได้ข้อความดิบ** ให้หยุดตรงนี้ แล้วกลับไปใช้ Audio Connector

---

## 1. เปิดเซิร์ฟเวอร์ให้ Genesys เรียกถึง (Mac ทดสอบ)

```bash
cd cc_ai_chat_hybrid_bot
export GENESYS_SECRET=$(openssl rand -hex 32)    # จดค่านี้ไว้ใส่ใน Genesys (ข้อ 2)
python3 -m channels.webchat.server --port 8000
#   Genesys Data Action (voice bot flow) on http://127.0.0.1:8000/api/genesys/turn
```

อีกหน้าต่างหนึ่ง เปิด tunnel ให้ได้ `https://` สาธารณะ:

```bash
cloudflared tunnel --url http://localhost:8000
#   https://xxxx-xxxx.trycloudflare.com   ← ที่อยู่นี้เปลี่ยนทุกครั้งที่รันใหม่
```

ทดสอบจากภายนอก (ควรได้คำทักทาย):

```bash
curl -s https://xxxx-xxxx.trycloudflare.com/api/genesys/turn \
  -H 'Content-Type: application/json' -H "x-bot-secret: $GENESYS_SECRET" \
  -d '{"sessionId":"test-1","text":""}'
```

| request | ความหมาย |
|---|---|
| `sessionId` | `Session.ConversationId` แยกแต่ละสาย |
| `text` | สิ่งที่ผู้โทรพูด ส่ง `""` ครั้งแรกเพื่อให้บอททักทาย |
| `format` | `speech` (ค่าเริ่มต้น: ตัวเลขและเงินเขียนเป็นคำให้ TTS อ่าน) หรือ `text` |

| response (string ทั้งหมด) | ค่า |
|---|---|
| `reply` | ประโยคที่ให้ Genesys พูด |
| `action` | `continue`, `handoff`, `end` |
| `handoffReason` | `agent`, `verify_failed`, `adapter_error`, `order_change_address` หรือรหัสหัวข้อ FAQ ที่โอน (`payment_arrangement`, `bill_detail`, `forgot_id`, `update_contact`, `cancel_service`) หรือว่าง |
| `verifiedPhone` | เบอร์ที่ยืนยันตัวตนผ่านแล้ว หรือว่าง |
| `expectsDigits` | `true` ระหว่างรอเบอร์โทร เลขบัตร หรือเลขคำสั่งซื้อ |
| `orderId`, `ticket` | ตอนโอน: เลขคำสั่งซื้อและเลขเรื่องที่คุยกันในสาย ให้เจ้าหน้าที่เห็น (ไม่บังคับ: เพิ่มใน output contract ถ้าต้องการใช้) |

บอทขัดข้องจะตอบ 200 + `action=handoff` เสมอ ผู้โทรจะไม่หลุดสาย อย่าเปิด `--ai` ตอนใช้กับ Data Action
เพราะคำตอบจาก AI อาจช้ากว่าที่ Data Action รอ

---

## 2. Data Action ใน Genesys

### 2.1 Integration

Admin → Integrations → **+ Integrations** → **Web Services Data Actions** → Install → ตั้งชื่อ เช่น
`Thai Bot API`

- **Configuration → Credentials → Configure:** Credential Type = **User Defined** เพิ่มฟิลด์ชื่อ `secret`
  ค่า = `GENESYS_SECRET` → Save
- เปลี่ยนสถานะเป็น **Active**

### 2.2 Action

Admin → Integrations → **Actions** → **Add Action** → เลือก integration `Thai Bot API` → ชื่อ `Thai Bot Turn`

**Contracts → Input** (JSON schema):

```json
{
  "type": "object",
  "properties": {
    "sessionId": {"type": "string"},
    "text": {"type": "string"}
  },
  "required": ["sessionId"]
}
```

**Contracts → Output:**

```json
{
  "type": "object",
  "properties": {
    "reply": {"type": "string"},
    "action": {"type": "string"},
    "handoffReason": {"type": "string"},
    "verifiedPhone": {"type": "string"},
    "expectsDigits": {"type": "string"},
    "orderId": {"type": "string"},
    "ticket": {"type": "string"}
  }
}
```

**Configuration → Request:**
- Request URL Template: `https://xxxx-xxxx.trycloudflare.com/api/genesys/turn`
- Method: **POST**
- Headers: `Content-Type: application/json` และ `x-bot-secret: ${credentials.secret}`
- Request Template:
  ```
  {"sessionId": "${input.sessionId}", "text": "$esc.jsonEncode(${input.text})"}
  ```
  `$esc.jsonEncode` กันเครื่องหมายคำพูดในสิ่งที่ผู้โทรพูดทำให้ JSON เสีย

**Configuration → Response:** ใช้ค่าเริ่มต้น (`successTemplate` = `${rawResult}`) เพราะ response แบนตรงกับ
output contract แล้ว

**Test:** ใส่ `sessionId=test-2`, `text=` (ว่าง) → Run Action ควรได้ `reply` เป็นคำทักทาย แล้ว **Publish**

---

## 3. Voice bot flow

Architect → **Bot Flow** (voice) → สร้างใหม่ เช่น `Thai Bot Voice` → Supported language **Thai (th-TH)**

### 3.1 ตัวแปรและ outputs

- ตัวแปรใน flow (String): `Flow.text` (ค่าเริ่มต้น `""`), `Flow.reply`, `Flow.action`
- **Bot flow outputs** (ประกาศใน Settings ของ flow): `Flow.handoffReason`, `Flow.verifiedPhone` (String)

### 3.2 Task `Turn` (วนทุกประโยค)

1. **Call Data Action** `Thai Bot Turn`
   - Inputs: `sessionId = Session.ConversationId`, `text = Flow.text`
   - Outputs: `reply → Flow.reply`, `action → Flow.action`, `handoffReason → Flow.handoffReason`,
     `verifiedPhone → Flow.verifiedPhone`
   - **Failure / Timeout:** Update Data `Flow.handoffReason = "adapter_error"` → **Exit Bot Flow**
2. **Switch** ตาม `Flow.action`:
   - `"handoff"` → **Communicate** `Flow.reply` → **Exit Bot Flow**
   - `"end"` → **Communicate** `Flow.reply` → **Exit Bot Flow**
   - อื่น ๆ (`"continue"`) → ข้อ 3
3. **ฟังประโยคถัดไป** ด้วยวิธีที่ใช้ได้จากข้อ 0 โดยตั้ง **prompt = `Flow.reply`** (Genesys พูดคำตอบแล้วฟังต่อทันที)
   แล้ว **Update Data** `Flow.text = <ค่าที่ได้>`
   - ตั้ง No Match / No Input ไม่ให้ bot flow ตอบเอง: ทาง No Match ให้ส่งข้อความว่างหรือข้อความที่ได้ไปให้บอทเรา
     บอทจะถามซ้ำหรือเสนอโอนเจ้าหน้าที่เองหลังไม่เข้าใจ 2 ครั้ง
4. **Loop** กลับไปข้อ 1 (Jump to Task `Turn`) ใส่ขีดจำกัดรอบ เช่น 30 รอบ แล้วเข้า handoff

Publish flow

### 3.3 รับเลขจากแป้นกด (ไม่บังคับ)

เมื่อ `Flow.expectsDigits == "true"` บอทกำลังรอเบอร์โทร เลขบัตร หรือเลขคำสั่งซื้อ ถ้าวิธีในข้อ 3 รับ DTMF ได้
ให้เปิดรับ DTMF ด้วย บอทรับตัวเลขได้ทั้งแบบพูดและแบบกด

---

## 4. Inbound Call flow

1. Architect → Inbound Call → flow เช่น `Thai Bot Voice Entry` → ภาษา **Thai**
2. **Call Bot Flow** → `Thai Bot Voice` → map outputs: `handoffReason → Flow.handoffReason`,
   `verifiedPhone → Flow.verifiedPhone`
3. หลัง Call Bot Flow:
   - `Flow.handoffReason` ไม่ว่าง → **Set Participant Data** (`verifiedPhone`, `handoffReason`) →
     **Set Screen Pop** (Script ที่แสดงค่าเหล่านี้) → **Transfer to ACD**
   - ว่าง (ผู้โทรลาแล้ว) → **Disconnect**
   - **Failure** → **Transfer to ACD** ผู้โทรจะไม่หลุดสาย
4. ผูกเบอร์ทดสอบ (DID) เข้ากับ flow นี้ที่ Admin → Telephony / Call Routing → Publish

---

## 5. โทรทดสอบ

ใช้สคริปต์เดียวกับ `handoff.md` ข้อ 6 (ข้อ 1–4, 6–8, 10) ดู log ในหน้าต่างเซิร์ฟเวอร์: บรรทัด
`genesys session=... in='...'` คือข้อความที่ Genesys ถอดได้ (เลขถูกปิดบัง) จดประโยคที่ถอดผิดไว้ เพื่อเพิ่มคำใน
`callcenter_bot/intents.py`

| อาการ | ดูที่ | วิธีแก้ |
|---|---|---|
| เข้าทาง Failure ของ Data Action ทันที | Data Action → Test | ที่อยู่ tunnel เปลี่ยน (รัน cloudflared ใหม่) หรือ secret ไม่ตรง (403) |
| `503 Genesys connector is off` | Test ของ Data Action | ยังไม่ได้ `export GENESYS_SECRET` ก่อนเปิดเซิร์ฟเวอร์ |
| บอทพูดแต่คำทักทายวน | log บรรทัด `in=''` | `Flow.text` ว่างทุกรอบ: วิธีดึงข้อความในข้อ 3 ใช้ไม่ได้ ย้อนไปข้อ 0 |
| บอทไม่เข้าใจบ่อย | log บรรทัด `in=` | Genesys ถอดภาษาไทยผิด: เพิ่มคำที่ถอดได้ใน `intents.py` หรือเลือก ASR ภายนอกให้ bot flow |
