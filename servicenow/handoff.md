# Handoff: ย้ายบอทเป็น ServiceNow scoped app (config-driven)

เอกสารนี้ใช้ส่งต่องานให้ session ที่จะออกแบบต่อ, deploy และแปลงโค้ด อ่านไฟล์นี้ก่อน แล้วค่อยเปิด `design.md`

| | |
|---|---|
| Repository | `gcat332/cc_ai_chat_hybrid_bot` branch `main` |
| Design | `servicenow/design.md` (revision 2) และ `servicenow/api-spec.md` |
| โค้ดต้นแบบ (Python) | commit `23eb025` → `callcenter_bot/` (ตัว engine), `channels/genesys/connector.py` (`handle_turn`) |
| Skill ที่ใช้ | `servicenow-design` (ออกแบบ, ห้ามต่อ instance) → `servicenow-deploy` (deploy ด้วย Fluent SDK) → `servicenow-test-cases` (ถ้าต้องการ) |
| สถานะ | Design ผ่าน gate 3A–3E แล้ว **ยังไม่ APPROVED** และ **ยังไม่ deploy** |

---

## 1. เป้าหมาย

ย้ายบอทศูนย์บริการลูกค้าธนาคารภาษาไทยแบบกฎ (rule-based) จาก Python ไปเป็น **scoped app ใน ServiceNow**
ให้ทำหน้าที่เป็น "สมอง" ของ Genesys voice Bot Flow แทนเซิร์ฟเวอร์ Python

**ข้อกำหนดหลักของผู้ใช้:** context, กลุ่มคำ (group of words), FAQ, ข้อความของบอท และเมนู ต้องเป็น **config ที่ end user แก้ได้จริง**
ผ่านฟอร์ม/รายการของ ServiceNow มีผลทันทีโดยไม่ต้องแก้โค้ดและไม่ต้อง deploy

- Genesys ยังเป็นตัวฟังและพูดภาษาไทย แล้วเรียก `POST /api/x_mfec3_ccbot/bot/turn` ทุก turn ด้วย Data Action
- **สัญญา request/response ต้องเหมือน `/api/genesys/turn` ของ Python ทุกฟิลด์** (`api-spec.md`)
- บอท **ไม่เปิด case เอง**: ส่งข้อมูลต่อให้ PayOff flow เดิมทาง participant data ของ Genesys

---

## 2. การตัดสินใจที่ได้แล้ว (Q1–Q8)

| # | เรื่อง | คำตอบผู้ใช้ | ผล |
|---|---|---|---|
| Q1 | Company code | `mfec3` | scope `x_mfec3_ccbot`; ชื่อตาราง ≤ 30 ตัวอักษร (template ใช้ `x_mfec3_ccbot_template`) |
| Q2 | ตารางข้อมูลธนาคาร | มีตารางเดิมใน instance แต่ **ไว้ก่อน** | ใช้ตาราง PoC 5 ตาราง (T14–T18) ใน scope ไปก่อน |
| Q3 | CSM จริง | **ใช้** | อ่าน `sn_customerservice_case` + `csm_consumer` (อ่านอย่างเดียว) ผ่าน cross-scope privilege 2 รายการ |
| Q4 | Release | เช็คตอน deploy | ตรวจ release และ JavaScript mode ของ scope ก่อน build |
| Q5 | เก็บบทสนทนา | **30 วัน** | `profile.retention_days = 30`, scheduled job ลบทุกวัน |
| Q6 | role | **ไม่แยก** (demo/PoC) | `x_mfec3_ccbot.admin` (ผู้ดูแลบอท) + `x_mfec3_ccbot.api` (Genesys) |
| Q7 | Genesys auth | **OAuth** | client credentials; checklist หลัง deploy ใน `api-spec.md` |
| Q8 | หน้าดูบทสนทนาย้อนหลัง (UC-12) | **"ไม่ต้องก็ได้มั้ง เดี๋ยวค่อยตัดสินใจ"** | **ยังไม่ปิด** แนวโน้มคือตัด ดูข้อ 3 |

## 3. งานที่ค้าง (ทำตามลำดับ)

1. **ยืนยัน Q8 กับผู้ใช้ (แนวโน้ม: ตัด)** ถ้าตัด ให้แก้ `design.md` ดังนี้:
   - ลบ UC-12 ออกจาก Section 0 และจาก 4A
   - ลบโมดูล `mod-conversations`, `mod-not-understood` (โมดูลเหลือ 13)
   - ลบฟิลด์ `conversation.misunderstood_lines` (ฟิลด์เหลือ 145) และ number config `conversation-number`
     แล้วเปลี่ยน display ของ conversation เป็น `session_id`
   - **ตาราง `conversation` ยังต้องมี** เพราะ UC-1 ใช้เก็บสถานะการสนทนา (REST เป็น stateless) และ UC-3/UC-13 ใช้ transcript กับ retention
   - แก้ยอดใน 2.20 และ 5.4 ให้ตรง แล้วรัน gate 3A–3E ใหม่
2. **ขอ "APPROVED"** จากผู้ใช้ (กฎของ skill: ห้าม deploy ถ้าไม่มีคำนี้)
3. **Deploy** ด้วย skill `servicenow-deploy` ต้องขอจากผู้ใช้: URL ของ instance + credential ที่ deploy ได้ และตรวจรายการ verify ใน 4B ก่อน
4. **แปลง engine** Python → Script Include 4 ตัว (ข้อ 5)
5. **สร้าง seed data** จากโค้ด Python อัตโนมัติ (ข้อ 6)
6. **เทียบผล:** test_script ใน ServiceNow ต้องให้ผลเหมือนบอท Python (ข้อ 7)
7. **ตั้งค่าหลัง deploy:** integration user + OAuth + แก้ Data Action ของ Genesys (checklist ใน `api-spec.md`)

---

## 4. ภาพรวม design (สรุป รายละเอียดอยู่ใน design.md)

**18 ตาราง**
- **Config (ผู้ใช้แก้ได้):** profile, intent, word_group, phrase, faq, template, menu, menu_option, context_rule, case_state_map
- **Runtime:** conversation, verify_failure
- **Test:** test_script (ปุ่ม Run test)
- **PoC:** customer, customer_phone, deposit_account, credit_card, loan

**ส่วนอื่น:** Script Include 4 · BR 11 · UI Policy 3 · UI Action 1 · Scripted REST 2 · cross-scope 2 · role 2 · ACL 73 · scheduled job 1 · app menu 1 + โมดูล 15

**แนวคิดหลัก**
- **กลุ่มคำเป็นตัวเดียวใช้ทุกที่:** `word_group.usage` บอกว่า engine เอากลุ่มไปใช้ทำอะไร
  เช่น `intent_keywords`, `faq_keywords`, `menu_keywords`, `context`, `yes`/`no`, `cancel`, `filler`, `polite`,
  `hesitate`, `dont_know`, `close_reason` (ใช้ `code`), `bank`/`loan_type`/`say_as` (ใช้ `phrase.value`), `digit_word`, `number_unit`
- **แต่ละคำ (phrase) ตั้งค่าได้:** `match_mode` (contains / whole_word / whole_line / starts_with), `not_after` (กัน "เปิด" ตรง "ปิด"),
  `max_line_length` (ตรงเฉพาะประโยคสั้น), `weight` (ว่าง = ความยาวคำ เหมือน Python)
  และ BR-3 เก็บ `match_key` (รูปที่ normalize แล้ว) ไว้ให้ engine เทียบ
- **พฤติกรรมของ intent:** `intent_type` + `behavior` เลือกจากพฤติกรรมที่ engine มี ดังนั้น intent ใหม่ไม่ต้องแก้โค้ด
- **ข้อความทุกประโยคอยู่ใน `template`** ตัวแปรที่ใช้ได้เสมอคือ `{P}{Q}{ME}{BRAND}{HOTLINE}{HOURS}` บวกตัวแปรเฉพาะของแต่ละ key
  และ BR-4 ไม่ยอมบันทึกถ้าใช้ตัวแปรที่ไม่รู้จัก
- **config มีผลทันที:** engine อ่าน config ที่ active ใหม่ทุก request ไม่มีขั้น publish
  (ถ้าผู้ใช้ต้องการภายหลัง ให้เพิ่มเป็น UC ใหม่)

---

## 5. การแปลง engine (Python → Script Include)

| Script Include | มาจาก (Python) | หมายเหตุ |
|---|---|---|
| `ThaiText` | `normalize.py`, `offers.py` | เลขไทย, ตัวอักษรยืด (ห้ามยุบตัวเลข), ตัดคำลงท้าย (`NOT_PARTICLE_AFTER`), compact, `spoken_digits`, `digits_only`, `phone_from_ani`/E.164, อ่านอัตรา/เงิน/จำนวนวัน/ชื่อธนาคาร **คำต่าง ๆ อ่านจาก word_group** (digit_word, number_unit, bank, polite) ไม่ hard-code |
| `ResponseRenderer` | `thai_format.py` (`speech_text`, `baht`, `thai_date`) | อ่านเลขทีละตัวเป็นกลุ่ม, บาท/สตางค์, นาฬิกา, เว้นจังหวะ (`.` หลังคำลงท้าย, `,` ระหว่างวลี, ไม่หยุดก่อนคำลงท้าย, ไม่หยุดกลางชื่อ BRAND/say_as) |
| `BotConfig` | `intents.py` (`detect`, `keyword_score`, `_matches`, `is_filler`, `is_fragment`, `yes_no`), `backend.faq_entries` | ให้คะแนนตาม phrase + match_mode/not_after/max_line_length; FAQ ชนะเมื่อคะแนนมากกว่า; intent เท่ากันใช้ `priority`; มีฟังก์ชันหาคำซ้ำให้ BR-3 |
| `BotEngine` | `bot.py`, `transcripts.py`, `backend.py`, `tables.valid_national_id`, `connector.handle_turn` | ลำดับต่อ turn ตาม design 1.4 และ docstring ของ `bot.py`; ยืนยันตัวตน (ANI + 4 ตัวท้าย / 13 หลัก + checksum / ล็อก); ขั้นตอน: `need_national_id`, `need_id4`, `need_case`, `confirm_intent`, `which_loan`, `loan_offer`, `loan_when`, `loan_mode`, `loan_reason`, `confirm_next`, `anything_else`; สร้าง participant data (`transcripts.PARTICIPANT_FIELDS`), summary/transcript ≤ `handoff_field_limit` |

**สิ่งที่ต้องรักษาให้เหมือนเดิม**
- **error ของบอท:** ตอบ HTTP 200 + `action=handoff`, `handoffReason=adapter_error` ไม่ส่ง 500 ให้ Genesys เพราะผู้โทรจะหลุดสาย
- **turn แรก:** `text` ว่าง → คำทักทาย; ส่ง `ani` มาทุก turn
- **ความเป็นส่วนตัว:** ตัวเลขส่วนบุคคลใน transcript และ log ต้องปิดบัง (`privacy.mask_digits`); `verify_failure` เก็บ SHA-256 ของเลขบัตร ไม่เก็บเลขตรง ๆ
- **case:** ต้องเป็นของลูกค้าที่ยืนยันตัวตนแล้วเท่านั้น (`case.consumer` ↔ `customer.consumer`) และถ้อยคำสถานะ case มาจาก `case_state_map`
- **ห้ามสร้าง/แก้ case ใน CSM** (อ่านอย่างเดียว)
- **โปรไฟล์เริ่มต้น:** ใช้ค่าจาก `config.py` ปัจจุบัน คือ เสียงผู้ชาย (ครับ/ครับ/ผม), `MAX_MISUNDERSTOOD=2`, verify 3 ครั้ง, ล็อก 3 ครั้งใน 30 นาที, `AGENT_HOURS=None`

**ความเร็ว:** engine ต้องตอบทันเวลาที่ Data Action ของ Genesys รอ ให้วัดเวลาโหลด config (~2,000 แถว) ตั้งแต่ build แรก
ถ้าช้า ให้ cache config ภายใน request และโหลดเฉพาะคอลัมน์ที่ใช้

---

## 6. Seed data (สร้างจากโค้ด ไม่พิมพ์เอง)

เขียนสคริปต์ (เช่น `tools/export_servicenow_seed.py`) อ่านค่าจาก Python ที่ `23eb025` แล้วสร้างข้อมูลตาม design 5.3:

| ข้อมูล | จำนวน |
|---|---|
| intent + คำ | 22 intent · 277 คำ |
| กลุ่มคำพิเศษ | ~20 กลุ่ม (cancel, yes/no, polite, filler, hesitate, dont_know, loan_type, close_reason + `REASON_CODES`, banks, digit/unit words, say_as) |
| context rule | 2 (deceased, third_party) |
| FAQ | 46 ข้อ (`data/seed_faq.sql`) |
| template | ~150 ข้อความจาก `bot.py` |
| เมนู | 7 เมนู (`CATEGORIES`, `MENU_CHOICES`, `LOAN/CLOSE/AMOUNT_MENU`, `config.MAIN_MENU`) |
| สถานะ case | 6 (`config.CASE_STATES`) |
| โปรไฟล์ | 1 |
| ข้อมูล PoC | `seed.sql` รวมลูกค้า C1–C5 ของ PayOff |

---

## 7. การเทียบผล (parity)

- แปลงบทสนทนาหลักจาก `tests/test_bot.py`, `tests/test_phrasings.py` และ `tests/test_genesys.py` (ส่วน `handle_turn`) เป็น `test_script` ราว 30 ชุด
- **เกณฑ์ผ่าน:** `action`, `handoffReason` และข้อความสุดท้ายตรงกับผลของบอท Python ชุดเดียวกัน
- รันเทสต์ Python เดิมเพื่อดูผลที่คาดไว้: `python -m unittest discover -s tests`

**ข้อมูลทดสอบหลัก**

| ลูกค้า | เบอร์ (ANI) | เลขบัตร 13 หลัก (4 ตัวท้าย) |
|---|---|---|
| พลอยใส | 0815493626 | 3294367792962 (2962) |
| สมชาย ใจงาม | 0812345678 | 1101700123456 (3456) |
| PayOff C2 สมหญิง | 0810000002 | 1100800000029 (0029) |
| ทดสอบ | 0636538939 | 1509900543215 (3215) |

---

## 8. ข้อควรระวัง

- **ห้าม extend OOTB table** และห้ามใช้ prefix `u_` (กฎของ skill) CSM ใช้ reference + อ่านอย่างเดียว
- **ห้ามเดา sys_id** และห้ามใส่ credential ในไฟล์ใด ๆ
- **ไม่อยู่ในขอบเขตรอบนี้:** เว็บแชท/GitHub Pages, Audio Connector + Azure, Bot Connector, AI fallback (ยังอยู่ใน repository เดิม)
- **คู่มือ Genesys เดิม** (`handoff.md` ที่ root, `channels/genesys/voice-bot-flow.md`) ยังใช้กับบอท Python ได้ ถ้าย้ายไป ServiceNow เสร็จ ให้อัปเดตเรื่อง URL และ OAuth
- **commit ทุกครั้ง:** ลงท้ายด้วยบรรทัด attribution ตามที่ session กำหนด และ push ขึ้น `main`
