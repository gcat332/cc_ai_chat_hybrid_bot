# Thai Call Center Bot (ServiceNow) — Design Document

> **สถานะ: รอรีวิว (revision 2)**: ตอบ Q1–Q7 แล้ว และ Gate 3A–3E ผ่านทั้งหมด (Section 4)
> เหลือ **Q8**: จะเก็บหน้าดูบทสนทนาย้อนหลัง (UC-12) ไว้ไหม (ดูตัวอย่างใน 1.8) ตอบแล้วพิมพ์ **APPROVED** เพื่อไป deploy ได้
> เป็น **demo / PoC**: role เดียวสำหรับผู้ดูแล และใช้ข้อมูลธนาคารชุด PoC
> ที่มา: repository `gcat332/cc_ai_chat_hybrid_bot` commit `23eb025` (บอทธนาคาร Python) ·
> แนวทาง: Option A (ย้ายบอทเป็น scoped app ใน ServiceNow) ·
> ข้อกำหนดหลักของผู้ใช้: **context, กลุ่มคำ (group of words), FAQ และข้อความของบอท ต้องเป็น config ที่ end user แก้ได้จริง ไม่ต้องแก้โค้ดและไม่ต้อง deploy**

---

## 0. Use Case Register (the traceability anchor)

| UC-id | Actor | Goal / outcome | Trigger | Acceptance signal |
|---|---|---|---|---|
| **UC-1** | ผู้โทร (ผ่าน Genesys voice Bot Flow) | คุยกับบอททีละประโยค: Genesys ส่งคำพูดที่ฟังได้มาให้ ServiceNow แล้วได้คำตอบกลับไปพูด | Data Action `POST /api/x_mfec3_ccbot/bot/turn` ทุก turn | ตอบกลับด้วยสัญญา (contract) เดียวกับ `/api/genesys/turn` ปัจจุบัน (Section 7) ภายใน ~1 วินาที, Genesys Bot Flow ไม่ต้องแก้นอกจาก URL และ auth |
| **UC-2** | ผู้โทร | ยืนยันตัวตน (เบอร์ที่โทรเข้า + เลขบัตร 4 ตัวท้าย หรือเลขบัตร 13 หลัก) แล้วสอบถามยอดค้างชำระ สินเชื่อ บัตรเครดิต ยอดเงินฝาก และสถานะเรื่องของตน | พูดหัวข้อสอบถาม | บอทอ่านข้อมูลของลูกค้าคนนั้นและตอบถูกต้อง, ข้อมูลคนอื่นไม่หลุด |
| **UC-3** | ผู้โทร | แจ้งคำขอที่ต้องใช้เจ้าหน้าที่ (ปิด/รีไฟแนนซ์สินเชื่อ, บัตรหาย ฯลฯ): บอทยืนยันความต้องการ ยืนยันตัวตน เก็บข้อมูล (สินเชื่อไหน เหตุผล ข้อเสนอธนาคารอื่น) แล้วโอนสาย | พูดคำขอ / ขอคุยกับเจ้าหน้าที่ / ตรงกับกฎบริบท (เช่น โทรแทน, เสียชีวิต) | `action=handoff` พร้อม participant data ของ PayOff (topic, kyc_result, loan_number, reason, …) ครบเหมือนปัจจุบัน |
| **UC-4** | ระบบ / Bot admin | ล็อกการยืนยันตัวตนของเลขบัตรที่ผิดซ้ำ N ครั้งใน M นาที และ admin ปลดล็อกได้ | ยืนยันตัวตนผิดครั้งที่ N | บอทโอนเจ้าหน้าที่แทนการถามซ้ำ, admin ลบรายการเพื่อปลดล็อก |
| **UC-5** | Bot admin | ดูแล **กลุ่มคำ (group of words)**: คำของแต่ละ intent, คำตอบรับ/ปฏิเสธ/ยกเลิก, คำเติม (เอ่อ, ครับ), คำบริบท (โทรแทน, เสียชีวิต, ขอคิดก่อน), ชื่อธนาคาร, เหตุผลปิดสินเชื่อ, คำอ่านออกเสียง | เพิ่ม/แก้/ปิดใช้คำ | มีผลกับ turn ถัดไปทันที ไม่ต้อง deploy, ได้คำเตือนเมื่อคำซ้ำกับ intent อื่น |
| **UC-6** | Bot admin | ดูแล **FAQ** (คำค้น, คำตอบ, ตอบเลยหรือโอนเจ้าหน้าที่) | เพิ่ม/แก้ FAQ | บอทตอบ FAQ ใหม่ได้ทันที, ถามแทรกกลางขั้นตอนได้ |
| **UC-7** | Bot admin | แก้ **ข้อความที่บอทพูด** (template) โดยใช้ตัวแปร เช่น `{name}`, `{amount}` | แก้ข้อความ | ระบบไม่ยอมบันทึกถ้าใช้ตัวแปรที่ไม่มี, บอทพูดข้อความใหม่ทันที |
| **UC-8** | Bot admin | ดูแล **เมนู**: คำถาม ปุ่ม และคำตอบสั้น ๆ ที่พาไปหัวข้อหรือเมนูย่อย | แก้เมนู | ผู้โทรพูด "สินเชื่อ" แล้วได้คำถามเมนูใหม่ |
| **UC-9** | Bot admin | ตั้งค่า **intent** (ชนิด, พฤติกรรม, ชื่อที่เจ้าหน้าที่เห็น, topic ของ ServiceNow, ลำดับ) และ **กฎบริบท (context rule)** | เพิ่ม/แก้ intent หรือกฎ | intent ใหม่ (เช่น คำขอใหม่) ทำงานได้โดยไม่แก้โค้ด |
| **UC-10** | Bot admin | ตั้งค่า **โปรไฟล์บอท**: เสียงผู้หญิง/ผู้ชาย (ค่ะ/ครับ), ชื่อธนาคาร, hotline, เวลาทำการ, ตารางเวลาเจ้าหน้าที่, ค่าจำกัดต่าง ๆ | แก้โปรไฟล์ | ใช้ได้ทันทีกับ turn ถัดไป |
| **UC-11** | Bot admin | **ทดสอบ** การตั้งค่าด้วยสคริปต์ทดสอบหลายประโยค ก่อนลูกค้าเจอ | กดปุ่ม "Run test" | เห็นคำตอบ intent และ action ของแต่ละบรรทัด พร้อมผล pass/fail |
| **UC-12** ⚠️ *รอ Q8 (ดูตัวอย่าง 1.8)* | Bot admin | ดูบทสนทนาย้อนหลัง (transcript, intent, เหตุผลโอนสาย) เพื่อหาประโยคที่บอทไม่เข้าใจแล้วเพิ่มคำ | เปิดรายการ Conversations | เห็นบทสนทนาและประโยคที่ไม่เข้าใจ |
| **UC-13** ✅ *Q5: 30 วัน* | ระบบ (ตาม PDPA) | ลบบทสนทนาและบันทึกการยืนยันตัวตนผิดที่เก่ากว่าระยะเก็บรักษา | Scheduled job รายวัน | ไม่มีข้อมูลเกินระยะเวลาที่กำหนด |
| **UC-14** | Bot admin | ตั้งค่าว่าสถานะ case แต่ละค่า บอทพูดกับลูกค้าว่าอะไร | แก้ตาราง | บอทอ่านสถานะ case ด้วยถ้อยคำใหม่ |
| **UC-15** ✅ *Q2: PoC ไปก่อน* | Bot admin | ดูแลข้อมูลธนาคารชุด PoC (ลูกค้า เบอร์ บัญชี บัตร สินเชื่อ) จนกว่าจะเปลี่ยนไปใช้ตารางเดิมของ instance | แก้ข้อมูล PoC | บอทตอบตามข้อมูลใหม่ |

> UC-12 และ UC-13 ผมเสนอเพิ่มเอง เพราะการเก็บสถานะการสนทนาใน ServiceNow (จำเป็นสำหรับ UC-1) ทำให้มีข้อมูลการสนทนาถาวรเกิดขึ้น
> ซึ่งต่างจากบอท Python ที่เก็บในหน่วยความจำ ถ้าไม่ต้องการ ให้ตัด component ที่ `serves:` เฉพาะ UC นั้นออก

---

## 1. Application Overview

| | |
|---|---|
| Name | Thai Call Center Bot |
| Package | `thai-call-center-bot` |
| Company code | `mfec3` (Q1 ✅): ต้องตรงกับ `glide.appcreator.company.code` ของ instance |
| Scope | `x_mfec3_ccbot` |
| Version | 1.0.0 |
| Description | บอทศูนย์บริการลูกค้าธนาคารภาษาไทยแบบกฎ (rule-based) ทำงานใน ServiceNow เป็น "สมอง" ให้ Genesys voice Bot Flow (Genesys ฟังและพูดภาษาไทย) โดยคำ, FAQ, ข้อความ, เมนู และกฎบริบทเป็น config ที่ผู้ใช้แก้เองได้ |

### 1.1 Architecture

```
ผู้โทร ─► Genesys Cloud voice Bot Flow (ASR/TTS ไทย)
             │ ทุก turn: Call Data Action (Web Services) ─ OAuth ─►
             ▼
  ServiceNow  POST /api/x_mfec3_ccbot/bot/turn   (Scripted REST, role: api)
             │
             ▼  BotEngine (Script Include, โค้ด: "พฤติกรรม")
             │    ├─ ThaiText          ทำความสะอาดข้อความไทย/ตัวเลขที่พูด
             │    ├─ BotConfig          อ่าน config ── ตาราง CONFIG (ผู้ใช้แก้ได้) ◄── Bot admin
             │    │                        profile · intent · word_group · phrase · faq
             │    │                        response_template · menu · menu_option · context_rule · case_state_map
             │    ├─ ResponseRenderer   เติมตัวแปรในข้อความ + จัดคำอ่านออกเสียง
             │    └─ ข้อมูล: ลูกค้า/บัญชี/บัตร/สินเชื่อ (PoC ใน scope) · sn_customerservice_case (CSM จริง)
             │
             ├─ conversation (สถานะการสนทนา + transcript)   verify_failure (ล็อกการยืนยันตัวตน)
             ▼
  ตอบ: reply · action (continue|handoff|end) · participant data ─► Genesys ─► Transfer to ACD ─► PayOff flow เดิม
```

### 1.2 หลักการแบ่ง "config" กับ "code"

| แก้ได้โดย end user (ตาราง config) | ยังเป็นโค้ด (Script Include) |
|---|---|
| คำของแต่ละ intent และน้ำหนักคำ | อัลกอริทึมให้คะแนนคำ และลำดับการตัดสินใจในแต่ละ turn |
| กลุ่มคำพิเศษ: ใช่/ไม่ใช่/ยกเลิก/คำเติม/คำสุภาพ/ขอคิดก่อน/ไม่ทราบ | การตรวจคำ "ใช่/ไม่ใช่" ที่มีคำเติมนำหน้า (ใช้กลุ่มคำจาก config) |
| กฎบริบท (โทรแทน, เสียชีวิต) → โอนพร้อมเหตุผล | ขั้นตอนการยืนยันตัวตน (ANI + 4 ตัวท้าย, เลขบัตร 13 หลัก + checksum, การล็อก) |
| FAQ ทั้งหมด (คำค้น, คำตอบ, ตอบเลย/โอน) | การอ่านข้อมูลธนาคาร และการตรวจว่า case เป็นของลูกค้าคนนั้น |
| ข้อความที่บอทพูดทุกประโยค (template + ตัวแปร) | ขั้นตอนเก็บข้อมูลคำขอปิดสินเชื่อ (สินเชื่อไหน, เมื่อไหร่, เหตุผล, ข้อเสนอธนาคารอื่น) |
| เมนูและปุ่ม | การแปลงคำพูดเป็นตัวเลข เช่น "สามจุดสองห้าเปอร์เซ็นต์" (คำตัวเลขเป็น config) |
| ชนิดและพฤติกรรมของ intent, ชื่อที่เจ้าหน้าที่เห็น, topic ของ ServiceNow | การสร้าง participant data และ summary/transcript ≤ 500 ตัวอักษร |
| ชื่อธนาคาร (คำพูด → ชื่อเขียน), ประเภทสินเชื่อ, เหตุผลปิดสินเชื่อ → code | การจัดคำอ่านออกเสียง (อ่านเลขทีละตัว, บาท/สตางค์, การเว้นจังหวะ) |
| คำอ่านออกเสียงพิเศษ (7-Eleven → เซเว่นอีเลฟเว่น) | — |
| โปรไฟล์: เสียง ค่ะ/ครับ, ชื่อธนาคาร, hotline, เวลาทำการ, ค่าจำกัด | — |
| ถ้อยคำสถานะ case | — |

> **intent ใหม่ไม่ต้องเขียนโค้ด** ถ้าใช้พฤติกรรมที่มีอยู่แล้ว (ตอบข้อความ / ยืนยันแล้วโอน / โอนด่วน / คำขอเรื่องสินเชื่อ / ตอบสอบถามข้อมูลธนาคาร 5 แบบ)
> ส่วน "การสอบถามข้อมูลแบบใหม่" (เช่น อ่านข้อมูลประกัน) ต้องเพิ่มพฤติกรรมใน BotEngine ก่อน แล้วจึงเลือกใช้ใน config ได้

### 1.3 ผลต่อ Genesys และงานย้ายข้อมูล

- **Genesys:** แก้ Data Action "Thai Bot Turn" แค่ 2 อย่าง ส่วน input/output schema เหมือนเดิมทุกตัว
  1. URL → `https://<instance>.service-now.com/api/x_mfec3_ccbot/bot/turn`
  2. Auth → **OAuth client credentials** (Q7): ใช้ Web Services Data Actions integration ชนิด User Defined OAuth
     ที่ขอ token จาก `https://<instance>.service-now.com/oauth_token.do`
- **ตั้งค่าใน ServiceNow หลัง deploy** (เป็นค่าของ platform ไม่ใช่ component ของ app ทำตาม checklist ใน `api-spec.md`):
  integration user (มีแค่ role `x_mfec3_ccbot.api`), OAuth Application Registry ชนิด client สำหรับ Genesys
  ผูกกับ integration user และเปิด client credentials grant ตามที่ release รองรับ (ตรวจตอน deploy, Q4)
- **ย้าย config เดิม:** ข้อมูลตั้งต้นทั้งหมด (22 intent / 277 คำ, กลุ่มคำพิเศษ, FAQ 46 ข้อ, ~150 ข้อความ, เมนู 7 ชุด, ธนาคาร, เหตุผลปิดสินเชื่อ, สถานะ case)
  จะสร้างเป็น seed data ตอน deploy ด้วยสคริปต์ที่สร้างจากโค้ด Python ปัจจุบัน ไม่ต้องพิมพ์เอง (ดู 5.3)
- **เทสต์เดิม:** เทสต์ Python ชุดสนทนา (`tests/test_bot.py`, `test_phrasings.py`) แปลงเป็น `test_script` ได้ และใช้เทียบผลก่อน/หลังย้ายได้
- **ไม่อยู่ในขอบเขต:** เว็บแชท/GitHub Pages, Audio Connector + Azure, Bot Connector, AI fallback ยังคงอยู่ใน repository เดิม

### 1.4 engine ใช้ config อย่างไร (ลำดับต่อหนึ่ง turn)

| ลำดับ | สิ่งที่ engine ทำ | config ที่ใช้ |
|---|---|---|
| 1 | ทำความสะอาดข้อความ: เลขไทย, ตัวอักษรยืด, ตัด**คำลงท้าย**, แปลง**เลขที่พูด**เป็นตัวเลข | word_group `polite`, `digit_word`, `number_unit` |
| 2 | ขอเจ้าหน้าที่? | intent ที่ `behavior=agent_handoff` (คำใน `keywords`) |
| 3 | เป็นแค่**คำเติม** (เอ่อ, ฮัลโหล)? → รอฟังต่อ | word_group `filler`, `polite`; template `filler_*` |
| 4 | ตรง**กฎบริบท**? (เรียงตาม `order`) → โอนพร้อม `handoff_reason` | context_rule + word_group `context` |
| 5 | อยู่ในขั้นตอน + พูด**ยกเลิก** (ทั้งประโยค) → ออกจากขั้นตอน | word_group `cancel` |
| 6 | อยู่ในขั้นตอน → อ่านคำตอบของขั้นตอนนั้น (ใช่/ไม่ใช่, ตัวเลข, สินเชื่อไหน, เหตุผล, ข้อเสนอ) ถ้าพูดเรื่องอื่นชัดเจน → เปลี่ยนหัวข้อ | `yes`, `no`, `yes_prefix`, `no_prefix`, `hesitate`, `dont_know`, `loan_type`, `close_reason`(+code), `bank`(value) |
| 7 | พูดตรงปุ่ม/คำเปิดเมนู → ถามเมนู หรือ (ถ้าเพิ่งถามเมนู) ใช้คำตอบสั้นของตัวเลือก | menu.opened_by, menu_option.answer_words → target |
| 8 | ให้คะแนน intent และ FAQ: รวมน้ำหนักคำที่ตรง (ว่าง = ความยาวคำ) ตาม `match_mode`, `not_after`, `max_line_length` แล้วคะแนนสูงสุดชนะ (เท่ากัน → `priority`) ส่วน FAQ ชนะเมื่อคะแนนมากกว่า intent | intent.keywords, faq.keywords |
| 9 | ทำตาม `behavior` ของ intent ที่ชนะ: ตอบ / ยืนยันตัวตนแล้วตอบ / ยืนยันคำขอแล้วโอน / โอนด่วน | intent, response_template |
| 10 | ไม่เข้าใจ → ขออภัย และหลัง `max_misunderstood` ครั้งเสนอเจ้าหน้าที่ บันทึกประโยคลง `misunderstood_lines` | profile, template `not_understood_*` |
| 11 | สร้างคำตอบ: template → แทนตัวแปร → คำอ่านออกเสียง (format=speech) | response_template, profile (P/Q/ME/BRAND/HOTLINE/HOURS), word_group `say_as` |
| 12 | ถ้าโอน: สร้าง participant data (topic จาก `servicenow_topic`, reason code จาก close_reason `code`, ธนาคารจาก `bank.value`) | intent/faq.servicenow_topic, word_group code/value |

**การเปลี่ยน config มีผลทันที** กับ turn ถัดไป เพราะ engine อ่าน config ที่ `active=true` ใหม่ทุก request (ไม่มีขั้น publish)
ทางป้องกันการแก้แล้วพังคือ BR ตรวจตอนบันทึก (BR-3/4/5/7) และ test_script (UC-11) ที่ควรรันก่อนแก้ของจริง
ถ้าภายหลังต้องการขั้น draft → publish ให้เพิ่มเป็น UC แยก

### 1.5 ตัวอย่าง: เพิ่มคำขอใหม่ "ขอใบรับรองดอกเบี้ย" โดยไม่แก้โค้ด

1. **Word Groups** → New: name "ขอใบรับรองดอกเบี้ย – คำ", usage `intent_keywords` → เพิ่ม Phrases "ใบรับรองดอกเบี้ย", "หนังสือรับรองดอกเบี้ย", "ลดหย่อนภาษี" (contains)
2. **Intents** → New: label "ขอใบรับรองดอกเบี้ยสินเชื่อบ้าน", name `interest_certificate`, type `request`, behavior `confirm_then_handoff`, keywords = กลุ่มในข้อ 1, servicenow_topic `homeloan_inquiry`
3. **Test Scripts** → New: ani `0815493626` (พลอยใส, เบอร์ที่ลงทะเบียน), บรรทัด "อยากได้ใบรับรองดอกเบี้ยไปลดหย่อนภาษี", "ใช่", "2962" (เลขบัตร 4 ตัวท้าย),
   expected action `handoff`, reason `interest_certificate` → **Run test** → pass
4. โทรจริงได้เลย ถ้าเป็นแค่ข้อมูลทั่วไป ใช้ **FAQ** (action answer) แทน ไม่ต้องสร้าง intent

### 1.6 กลุ่มข้อความ (response_template) ที่ seed ให้

| กลุ่ม key | ตัวอย่าง key | ตัวแปรที่ใช้ได้ (นอกจาก `{P}{Q}{ME}{BRAND}{HOTLINE}{HOURS}`) |
|---|---|---|
| ทักทาย/ปิด | `greeting`, `goodbye`, `thanks`, `anything_else` | — |
| ยืนยันตัวตน | `ask_id4_registered_phone`, `ask_national_id`, `verify_ok`, `verify_retry`, `verify_failed_handoff`, `verify_locked` | `{name}`, `{attempts_left}` |
| สอบถาม | `balance_due_card`, `loan_info_one`, `loan_info_choose`, `card_info`, `deposit_balance`, `case_status`, `case_not_found` | `{name}`, `{amount}`, `{due_date}`, `{loan}`, `{rate}`, `{installment}`, `{account}`, `{case}`, `{status}` |
| คำขอ | `confirm_request`, `request_handoff`, `loan_which`, `loan_when`, `loan_reason`, `loan_offer`, `loan_hesitate`, `loan_not_active` | `{request}`, `{loan}`, `{days}`, `{bank}` |
| เมนู/ไม่เข้าใจ | `menu_main`, `not_understood_1`, `not_understood_offer_agent`, `filler_wait` | `{choices}` |
| โอนสาย | `handoff_agent`, `handoff_after_hours`, `urgent_card_lost`, `urgent_unauthorized` | `{request}`, `{hours}` |
| ข้อมูลทั่วไป | `payment_channels`, `hours` | — |

### 1.7 Decisions (คำตอบของ Q1–Q8)

| # | คำถาม | คำตอบ | ผลใน design |
|---|---|---|---|
| Q1 | Company code | `mfec3` | scope `x_mfec3_ccbot`; ชื่อตารางทุกตัวไม่เกิน 30 ตัวอักษร (template ใช้ `x_mfec3_ccbot_template`) |
| Q2 | ตารางข้อมูลธนาคาร | มีตารางเดิมใน instance แต่**ไว้ก่อน** | ใช้ตาราง PoC T14–T18 ใน scope ไปก่อน การเปลี่ยนไปใช้ตารางเดิมเป็นงานรอบถัดไป: แก้เฉพาะส่วนอ่านข้อมูลใน BotEngine และ reference `conversation.customer` |
| Q3 | ใช้ CSM จริง | **ใช่** | อ่าน `sn_customerservice_case` จริง และผูกลูกค้ากับ `csm_consumer` (`customer.consumer`) ต้องมีสิทธิ์อ่านข้าม scope (2.19) |
| Q4 | Release | เช็คตอน deploy | servicenow-deploy ตรวจ release และ JavaScript mode ของ scope ก่อน build (4B, B4) |
| Q5 | เก็บบทสนทนา | **30 วัน** | `profile.retention_days = 30`, SJ-1 |
| Q6 | แยก role | **ไม่แยก** (demo/PoC) | role เดียว `x_mfec3_ccbot.admin` + `x_mfec3_ccbot.api` สำหรับ Genesys |
| Q7 | Genesys auth | **OAuth** | OAuth client credentials ผูกกับ integration user ที่มี role `api` (ตั้งค่า platform หลัง deploy, ดู 1.3 และ `api-spec.md`) |
| Q8 | หน้าดูบทสนทนาย้อนหลัง | **ขอดูตัวอย่าง** | ตัวอย่างใน 1.8 ตอนนี้ยังรวมไว้ใน design ถ้าไม่ต้องการ ให้ตัด: `mod-conversations`, `mod-not-understood`, ฟิลด์ `misunderstood_lines`, number config BOTC (ตาราง conversation ยังต้องมี เพราะ UC-1 ใช้เก็บสถานะ) |

### 1.8 ตัวอย่าง UC-12: หน้าดูบทสนทนาย้อนหลัง (ข้อมูลสมมติ)

**Thai Call Center Bot › Conversations** (เรียงจากล่าสุด)

| Number | Last turn | State | Caller | Customer | Handoff reason | Turns |
|---|---|---|---|---|---|---|
| BOTC0001042 | 24/11 14:32 | handed_off | +6681xxx0002 | สมหญิง | loan_close | 9 |
| BOTC0001041 | 24/11 14:20 | ended | +6681xxx3626 | พลอยใส | — | 5 |
| BOTC0001040 | 24/11 14:05 | handed_off | +6689xxx1122 | — | agent | 4 |

**เปิด BOTC0001042** (read-only)
- **Outcome:** handoff_reason `loan_close` · topics `loan_info,loan_close` · summary "ยืนยันตัวตนแล้ว (เบอร์+4 ตัวท้าย) | ต้องการปิดบัญชีสินเชื่อบ้าน | รีไฟแนนซ์ไปธนาคารอื่น (กสิกรไทย)"
- **Transcript:**
  ```
  ลูกค้า: ดอกเบี้ยบ้านตอนนี้เท่าไหร่
  บอท:   ขอเลขบัตรประชาชน 4 ตัวท้าย เพื่อยืนยันตัวตนครับ
  ลูกค้า: xxxx
  บอท:   คุณสมหญิง สินเชื่อบ้านลงท้าย 0002 คงเหลือ 800,000 บาท ดอกเบี้ย 5.5% ...
  ลูกค้า: งั้นขอปิดเลย จะย้ายไปกสิกร
  บอท:   ต้องการปิดบัญชีสินเชื่อบ้าน ใช่ไหมครับ
  ...
  ```
- **Not understood:** `ขอดูสเตทเมนต์ย้อนหลัง`

**Thai Call Center Bot › Not Understood**: บทสนทนาที่มีประโยคที่บอทไม่เข้าใจ ใช้หาคำมาเติม

| Number | Last turn | Not understood |
|---|---|---|
| BOTC0001042 | 24/11 14:32 | ขอดูสเตทเมนต์ย้อนหลัง |
| BOTC0001038 | 24/11 13:10 | บัตรกดเงินสดใช้ไม่ได้ · ตู้กลืนบัตร |

> วิธีใช้: admin เห็น "ตู้กลืนบัตร" ซ้ำหลายสาย → เพิ่มเป็นคำในกลุ่มของ intent `card_lost` หรือสร้าง FAQ ใหม่ → รัน test script → สายถัดไปบอทเข้าใจ
> ตัวเลขส่วนบุคคลใน transcript ถูกปิดบัง และข้อมูลถูกลบอัตโนมัติหลัง 30 วัน (UC-13)

---

## 2. Component Inventory

ทุก component มี key คงที่ และ `serves:` ระบุ UC ส่วน scope ใช้ `x_mfec3_ccbot`

### 2.1 Tables

| # | Key | Table | Label | Display | กลุ่ม | serves |
|---|---|---|---|---|---|---|
| T1 | `profile-table` | `x_mfec3_ccbot_profile` | Bot Profile | `name` | Config | UC-10 |
| T2 | `intent-table` | `x_mfec3_ccbot_intent` | Intent | `label` | Config | UC-9, UC-1 |
| T3 | `word-group-table` | `x_mfec3_ccbot_word_group` | Word Group | `name` | Config | UC-5 |
| T4 | `phrase-table` | `x_mfec3_ccbot_phrase` | Phrase | `phrase` | Config | UC-5 |
| T5 | `faq-table` | `x_mfec3_ccbot_faq` | FAQ | `title` | Config | UC-6 |
| T6 | `template-table` | `x_mfec3_ccbot_template` | Response Template | `key` | Config | UC-7 |
| T7 | `menu-table` | `x_mfec3_ccbot_menu` | Menu | `name` | Config | UC-8 |
| T8 | `menu-option-table` | `x_mfec3_ccbot_menu_option` | Menu Option | `button_label` | Config | UC-8 |
| T9 | `context-rule-table` | `x_mfec3_ccbot_context_rule` | Context Rule | `name` | Config | UC-9, UC-3 |
| T10 | `case-state-table` | `x_mfec3_ccbot_case_state_map` | Case Status Wording | `customer_text` | Config | UC-14 |
| T11 | `conversation-table` | `x_mfec3_ccbot_conversation` | Bot Conversation | `number` | Runtime | UC-1, UC-12 |
| T12 | `verify-failure-table` | `x_mfec3_ccbot_verify_failure` | Verify Failure | `failed_at` | Runtime | UC-4 |
| T13 | `test-script-table` | `x_mfec3_ccbot_test_script` | Test Script | `name` | Testing | UC-11 |
| T14 | `customer-table` | `x_mfec3_ccbot_customer` | Customer (PoC) | `first_name` | Bank data (PoC) | UC-2, UC-15 |
| T15 | `customer-phone-table` | `x_mfec3_ccbot_customer_phone` | Customer Phone (PoC) | `phone` | Bank data (PoC) | UC-2, UC-15 |
| T16 | `deposit-table` | `x_mfec3_ccbot_deposit_account` | Deposit Account (PoC) | `account_no` | Bank data (PoC) | UC-2, UC-15 |
| T17 | `card-table` | `x_mfec3_ccbot_credit_card` | Credit Card (PoC) | `card_name` | Bank data (PoC) | UC-2, UC-15 |
| T18 | `loan-table` | `x_mfec3_ccbot_loan` | Loan (PoC) | `loan_no` | Bank data (PoC) | UC-2, UC-3, UC-15 |

> ทุกตารางเป็น standalone (ไม่ extend OOTB) และ `allowWebServiceAccess = false` เพราะ Genesys เรียกผ่าน Scripted REST เท่านั้น ไม่ผ่าน Table API

### 2.2 Fields

#### T1 `x_mfec3_ccbot_profile`: Bot Profile (ใช้แถวที่ `active=true` ได้แถวเดียว)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `name` | Name | string(100) | ✓ | — | display | UC-10 |
| `active` | Active | boolean | | `false` | มีได้แถวเดียว (BR-2) | UC-10 |
| `voice_gender` | Voice | choice | ✓ | `male` | male/female → ค่าเริ่มต้นของคำลงท้าย (BR-1) | UC-10 |
| `statement_particle` | Statement particle | string(10) | ✓ | `ครับ` | ใช้แทน `{P}` | UC-10, UC-7 |
| `question_particle` | Question particle | string(10) | ✓ | `ครับ` | ใช้แทน `{Q}` | UC-10, UC-7 |
| `self_pronoun` | Self pronoun | string(10) | ✓ | `ผม` | ใช้แทน `{ME}` | UC-10, UC-7 |
| `brand_name` | Brand name | string(100) | | — | `{BRAND}` ในคำทักทาย | UC-10 |
| `hotline` | Hotline | string(40) | | — | `{HOTLINE}` | UC-10 |
| `hours_text` | Service hours (spoken) | string(200) | | — | `{HOURS}` | UC-10 |
| `agent_schedule` | Agent schedule | reference → `cmn_schedule` | | — | ว่าง = โอนได้ตลอด; cascade `clear` | UC-10, UC-3 |
| `max_misunderstood` | Misunderstood before offering agent | integer | ✓ | `2` | | UC-10 |
| `max_verify_attempts` | Verify attempts per call | integer | ✓ | `3` | | UC-10, UC-4 |
| `verify_lock_attempts` | Failures that lock an ID | integer | ✓ | `3` | | UC-10, UC-4 |
| `verify_lock_minutes` | Lock window (minutes) | integer | ✓ | `30` | | UC-10, UC-4 |
| `max_case_misses` | Case numbers not found before handoff | integer | ✓ | `3` | | UC-10 |
| `session_timeout_minutes` | Conversation timeout (minutes) | integer | ✓ | `30` | | UC-10, UC-1 |
| `default_reply_format` | Default reply format | choice | ✓ | `speech` | speech/text (เมื่อ request ไม่ส่ง `format`) | UC-1 |
| `handoff_field_limit` | Participant data limit (chars) | integer | ✓ | `500` | ข้อจำกัดของ Genesys Set Participant Data | UC-3 |
| `retention_days` | Keep conversations (days) | integer | ✓ | `30` | Q5 | UC-13 |

#### T2 `x_mfec3_ccbot_intent`: Intent
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `label` | Label (Thai) | string(100) | ✓ | — | display; ชื่อที่เจ้าหน้าที่เห็นและบอทใช้ยืนยัน เช่น "ปิดบัญชีสินเชื่อ" | UC-9, UC-3 |
| `name` | Name (code) | string(60) | ✓ unique | — | `^[a-z_]+$`, ส่งให้ Genesys เป็น `handoffReason` (BR-5) | UC-9, UC-1 |
| `intent_type` | Type | choice | ✓ | `request` | ดู 2.3 | UC-9 |
| `behavior` | Behavior | choice (dependent on `intent_type`) | ✓ | — | ดู 2.3: พฤติกรรมของ engine | UC-9 |
| `keywords` | Keywords | reference → `x_mfec3_ccbot_word_group` | ✓ | — | refQual simple `usage=intent_keywords^active=true`; cascade `restrict` | UC-5, UC-9 |
| `response_template` | Response | reference → `x_mfec3_ccbot_template` | | — | ใช้กับ type information/conversation/urgent (UI Policy-1); cascade `restrict` | UC-9, UC-7 |
| `servicenow_topic` | ServiceNow topic | choice | ✓ | `other` | participant data `topic` | UC-3 |
| `priority` | Priority | integer | ✓ | `100` | ตัดสินเมื่อคะแนนเท่ากัน (น้อย = ก่อน) | UC-9 |
| `builtin` | Built-in | boolean | | `false` | read-only; intent ที่ engine อ้างถึงด้วยชื่อ ลบไม่ได้ (ACL) | UC-9 |
| `active` | Active | boolean | | `true` | | UC-9 |

#### T3 `x_mfec3_ccbot_word_group`: Word Group (กลุ่มคำ)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `name` | Name | string(100) | ✓ unique | — | display เช่น "ปิดบัญชีสินเชื่อ – คำ", "คำตอบรับ (ใช่)" | UC-5 |
| `usage` | Usage | choice | ✓ | `intent_keywords` | engine อ่านกลุ่มตาม usage (2.3) | UC-5 |
| `code` | Output code | string(60) | | — | ค่าที่ engine ได้เมื่อคำในกลุ่มตรง เช่น `refinance` (usage close_reason) | UC-5, UC-3 |
| `order` | Order | integer | ✓ | `100` | ลำดับตรวจ (กลุ่ม usage เดียวกัน, ตัวแรกที่ตรงชนะ) | UC-5 |
| `description` | Description | multiline(4000) | | — | ใช้ทำอะไร | UC-5 |
| `active` | Active | boolean | | `true` | | UC-5 |

#### T4 `x_mfec3_ccbot_phrase`: Phrase (คำในกลุ่ม)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `phrase` | Phrase | string(200) | ✓ | — | display; คำตามที่ผู้ใช้พิมพ์ | UC-5 |
| `word_group` | Word group | reference → `x_mfec3_ccbot_word_group` | ✓ | — | cascade `delete` | UC-5 |
| `match_mode` | Match | choice | ✓ | `contains` | contains / whole_word / whole_line / starts_with | UC-5 |
| `match_key` | Match key | string(200) | | — | read-only; รูปที่ normalize แล้ว (BR-3) ที่ engine ใช้เทียบ | UC-5, UC-1 |
| `value` | Mapped value | string(200) | | — | เช่น ชื่อธนาคาร "กสิกรไทย", ประเภทสินเชื่อ "บ้าน", คำอ่าน "เซเว่นอีเลฟเว่น" | UC-5 |
| `not_after` | Not after | string(20) | | — | ไม่นับถ้าตัวอักษรข้างหน้าเป็นตัวนี้ เช่น `เ` (กัน "เปิดบัญชี" ตรง "ปิดบัญชี") | UC-5 |
| `max_line_length` | Only in lines up to (chars) | integer | | — | ตรงเฉพาะประโยคสั้น เช่น "ยอด" เดี่ยว ๆ ≤ 12 | UC-5, UC-8 |
| `weight` | Weight | integer | | — | ว่าง = ความยาวคำ (เหมือนปัจจุบัน) | UC-5 |
| `active` | Active | boolean | | `true` | | UC-5 |

#### T5 `x_mfec3_ccbot_faq`: FAQ
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `title` | Title | string(150) | ✓ | — | display | UC-6 |
| `topic` | Topic code | string(60) | ✓ unique | — | `^[a-z_]+$` (BR-5) → handoffReason เมื่อ action=handoff | UC-6, UC-3 |
| `keywords` | Keywords | reference → word_group | ✓ | — | refQual `usage=faq_keywords^active=true`; cascade `restrict` | UC-6, UC-5 |
| `answer` | Answer | multiline(4000) | ✓ | — | ใช้ตัวแปร `{P}` `{Q}` `{ME}` ได้ | UC-6 |
| `action` | Action | choice | ✓ | `answer` | answer / handoff | UC-6, UC-3 |
| `servicenow_topic` | ServiceNow topic | choice | ✓ | `other` | ใช้เมื่อ handoff | UC-3 |
| `active` | Active | boolean | | `true` | | UC-6 |

#### T6 `x_mfec3_ccbot_template`: Response Template (ข้อความที่บอทพูด)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `key` | Key | string(80) | ✓ unique | — | display; engine เรียกด้วย key เช่น `ask_national_id` | UC-7 |
| `text` | Text | multiline(4000) | ✓ | — | ข้อความที่แสดง/อ่าน มีตัวแปร `{...}` | UC-7 |
| `speech_text` | Speech override | multiline(4000) | | — | ถ้าว่าง ใช้ `text` แล้วจัดคำอ่านอัตโนมัติ | UC-7 |
| `quick_replies` | Buttons | string(500) | | — | คั่นด้วย `\|` (ช่องทางแชท/ทดสอบ) | UC-7 |
| `placeholders` | Allowed placeholders | string(300) | | — | read-only; ตัวแปรที่ใช้ได้ใน key นี้ (BR-4 ตรวจ) | UC-7 |
| `usage_note` | Where it is said | multiline(4000) | | — | read-only; อธิบายจุดที่บอทพูด | UC-7 |
| `builtin` | Built-in | boolean | | `false` | read-only; ลบไม่ได้ (ACL) | UC-7 |

#### T7 `x_mfec3_ccbot_menu`: Menu
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `name` | Name | string(80) | ✓ unique | — | display เช่น `main`, `loan`, `card`, `amount`, `close_account` | UC-8 |
| `question` | Question | multiline(4000) | ✓ | — | ที่บอทถาม มี `{Q}` ได้ | UC-8 |
| `opened_by` | Opened by | reference → word_group | | — | refQual `usage=menu_keywords`; คำที่เปิดเมนูนี้ เช่น "สินเชื่อ" (whole_line), "ยอด" (max 12) | UC-8 |
| `is_main` | Main menu | boolean | | `false` | ปุ่มของเมนูหลักแสดงตอนทักทาย/ไม่เข้าใจ (มีได้หนึ่งเมนู, BR-6) | UC-8 |
| `active` | Active | boolean | | `true` | | UC-8 |

#### T8 `x_mfec3_ccbot_menu_option`: Menu Option
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `button_label` | Button | string(100) | ✓ | — | display; ข้อความปุ่ม (พูดตรงกับปุ่ม = เลือก) | UC-8 |
| `menu` | Menu | reference → menu | ✓ | — | cascade `delete` | UC-8 |
| `answer_words` | Short answers | reference → word_group | | — | refQual `usage=menu_keywords`; คำตอบสั้น ๆ หลังคำถามเมนู เช่น "ปิด", "ย้าย" | UC-8 |
| `target_intent` | Go to intent | reference → intent | | — | cascade `restrict`; ต้องมี target อย่างใดอย่างหนึ่ง (BR-7) | UC-8 |
| `target_menu` | Go to menu | reference → menu | | — | cascade `restrict` | UC-8 |
| `order` | Order | integer | ✓ | `100` | ลำดับปุ่มและลำดับตรวจคำตอบ | UC-8 |
| `active` | Active | boolean | | `true` | | UC-8 |

#### T9 `x_mfec3_ccbot_context_rule`: Context Rule (กฎบริบท)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `name` | Name | string(100) | ✓ | — | display เช่น "เจ้าของบัญชีเสียชีวิต" | UC-9 |
| `words` | Words | reference → word_group | ✓ | — | refQual `usage=context`; cascade `restrict` | UC-9, UC-5 |
| `applies_when` | Applies when | choice | ✓ | `always` | always / with_topic (มีหัวข้อหรืออยู่ในขั้นตอนแล้ว) | UC-9 |
| `handoff_reason` | Handoff reason | string(60) | ✓ | — | `^[a-z_]+$` (BR-5) เช่น `deceased`, `third_party` | UC-9, UC-3 |
| `request_note` | Note for agent | string(200) | ✓ | — | เช่น "โทรแทนเจ้าของบัญชี" | UC-3 |
| `response_template` | Response | reference → template | ✓ | — | ประโยคก่อนโอน; cascade `restrict` | UC-9, UC-7 |
| `order` | Order | integer | ✓ | `100` | ตรวจตามลำดับ ตัวแรกที่ตรงชนะ | UC-9 |
| `active` | Active | boolean | | `true` | | UC-9 |

#### T10 `x_mfec3_ccbot_case_state_map`: Case Status Wording
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `customer_text` | Said to customer | string(200) | ✓ | — | display เช่น "กำลังดำเนินการ" | UC-14 |
| `state_value` | Case state value | integer | ✓ unique | — | ค่าของ `sn_customerservice_case.state` (1, 10, 18, 6, 3, 7) | UC-14 |
| `state_name` | State name | string(60) | | — | เช่น Open (อ้างอิง) | UC-14 |
| `is_done` | Finished state | boolean | | `false` | Resolved/Closed/Cancelled | UC-14, UC-2 |
| `is_awaiting_info` | Awaiting customer | boolean | | `false` | บอทเสนอโอนเจ้าหน้าที่ | UC-14, UC-2 |

#### T11 `x_mfec3_ccbot_conversation`: Bot Conversation (runtime; engine เป็นผู้เขียน)
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `number` | Number | string(40) | | auto | display; auto-number BOTC | UC-12 |
| `session_id` | Session ID | string(256) | ✓ unique | — | Genesys `Session.ConversationId` (หรือ `test-…`) | UC-1 |
| `channel` | Channel | choice | ✓ | `genesys_voice` | genesys_voice / test | UC-1, UC-11 |
| `state` | State | choice | ✓ | `active` | active / handed_off / ended / expired | UC-1, UC-12 |
| `ani` | Caller number | string(40) | | — | E.164 | UC-2 |
| `customer` | Verified customer | reference → customer (PoC) | | — | cascade `clear` | UC-2, UC-12 |
| `verified_by` | Verified by | choice | | — | ani_last4 / national_id | UC-2, UC-3 |
| `flow` | Flow | string(60) | | — | read-only (engine) | UC-1 |
| `step` | Step | string(60) | | — | read-only (engine) | UC-1 |
| `context_json` | Context | multiline(4000) | | `{}` | read-only; slots/ตัวนับ/เมนูค้าง (JSON) | UC-1 |
| `topics` | Topics | string(500) | | — | intent ที่ถามในสายนี้ คั่นด้วย `,` | UC-3, UC-12 |
| `misunderstood_lines` | Not understood | multiline(4000) | | — | ประโยคที่บอทไม่เข้าใจ (ใช้เพิ่มคำ) | UC-12, UC-5 |
| `transcript` | Transcript | multiline(4000) | | — | 4000 ตัวอักษรท้ายสุด; ตัวเลขส่วนบุคคลถูกปิดบัง | UC-3, UC-12 |
| `handoff_reason` | Handoff reason | string(60) | | — | | UC-3, UC-12 |
| `summary` | Summary for agent | string(500) | | — | | UC-3 |
| `turn_count` | Turns | integer | | `0` | | UC-12 |
| `last_turn_at` | Last turn | datetime | | — | ใช้คำนวณ timeout | UC-1, UC-13 |

#### T12 `x_mfec3_ccbot_verify_failure`: Verify Failure
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `failed_at` | Failed at | datetime | ✓ | `javascript:new GlideDateTime().getValue()` | display | UC-4 |
| `identity_hash` | Identity (hashed) | string(64) | ✓ | — | SHA-256 ของเลขบัตร: ไม่เก็บเลขบัตรตรง ๆ (PDPA) | UC-4 |
| `identity_last4` | ID last 4 | string(4) | | — | ให้ admin หาแถวที่จะปลดล็อก | UC-4 |
| `conversation` | Conversation | reference → conversation | | — | cascade `clear` | UC-4, UC-12 |

#### T13 `x_mfec3_ccbot_test_script`: Test Script
| Element | Label | Type | Mand. | Default | Notes | serves |
|---|---|---|---|---|---|---|
| `name` | Name | string(150) | ✓ | — | display | UC-11 |
| `ani` | Caller number | string(40) | | — | จำลองเบอร์ที่โทรเข้า | UC-11 |
| `utterances` | Lines (one per line) | multiline(4000) | ✓ | — | ประโยคผู้โทร บรรทัดละประโยค | UC-11 |
| `expected_action` | Expected final action | choice | | — | continue / handoff / end | UC-11 |
| `expected_reason` | Expected handoff reason | string(60) | | — | | UC-11 |
| `expected_text` | Last reply contains | string(200) | | — | | UC-11 |
| `last_status` | Last result | choice | | `not_run` | not_run / pass / fail | UC-11 |
| `last_result` | Result | multiline(4000) | | — | read-only; ต่อบรรทัด: ผู้โทร → intent → คำตอบ → action | UC-11 |
| `last_run_at` | Last run | datetime | | — | read-only | UC-11 |

#### T14–T18: Bank data (PoC): ใช้ไปก่อนตาม Q2 รอบถัดไปจะเปลี่ยนไปใช้ตารางเดิมของ instance และตัดตารางเหล่านี้
| Table | Fields (type) | serves |
|---|---|---|
| T14 customer | `national_id` string(13) ✓ unique · `title` string(20) · `first_name` string(100) ✓ display · `last_name` string(100) · `segment` choice (mass/wealth) · `consumer` reference → `csm_consumer` (CSM, cascade `clear`; BotEngine ใช้ตรวจว่า case เป็นของลูกค้าคนนี้) | UC-2, UC-15 |
| T15 customer_phone | `phone` phone_safe(10) ✓ unique display · `customer` ref → customer ✓ (cascade `delete`) · `is_main` boolean · `note` string(100) | UC-2, UC-15 |
| T16 deposit_account | `account_no` string(10) ✓ unique display · `customer` ref ✓ (cascade `delete`) · `account_type` choice (savings/fixed/current) · `balance` currency · `status` choice (normal/frozen/closed) | UC-2, UC-15 |
| T17 credit_card | `card_name` string(60) ✓ display · `card_last4` string(4) ✓ (ไม่เก็บเลขบัตรเต็ม, PCI) · `customer` ref ✓ (cascade `delete`) · `credit_limit` currency · `available_credit` currency · `outstanding` currency · `minimum_due` currency · `due_date` date · `status` choice (normal/suspended/cancelled) | UC-2, UC-15 |
| T18 loan | `loan_no` string(30) ✓ unique display · `customer` ref ✓ (cascade `delete`) · `loan_type` choice (home/personal) · `outstanding_principal` currency · `interest_rate` decimal · `monthly_installment` currency · `next_due_date` date · `remaining_months` integer · `status` choice (normal/closed) | UC-2, UC-3, UC-15 |

### 2.3 Choices

| Table.field | Values (value → label) | none | serves | consumer |
|---|---|---|---|---|
| profile.`voice_gender` | male → ชาย (ครับ/ผม) · female → หญิง (ค่ะ/คะ/ดิฉัน) | no | UC-10 | BR-1 |
| profile.`default_reply_format` | speech → อ่านออกเสียง · text → ข้อความ | no | UC-1 | BotEngine |
| intent.`intent_type` | inquiry → สอบถามข้อมูล (ต้องยืนยันตัวตน) · request → คำขอ (ยืนยันแล้วโอน) · urgent → คำขอด่วน (ไม่ถามยืนยัน) · information → ตอบข้อมูลทั่วไป · conversation → ทักทาย/ขอบคุณ/ลา · system → ระบบ (เจ้าหน้าที่, ยกเลิก) | no | UC-9 | BotEngine, UI Policy-1 |
| intent.`behavior` (dependent on `intent_type`) | inquiry: `answer_balance_due`, `answer_loan_info`, `answer_card_info`, `answer_deposit_balance`, `answer_case_status` · request: `confirm_then_handoff`, `loan_request` (เก็บข้อมูลสินเชื่อก่อนโอน) · urgent: `urgent_handoff` · information: `say_template` · conversation: `say_template`, `say_and_end` · system: `agent_handoff`, `cancel_step` | no | UC-9 | BotEngine |
| intent/faq.`servicenow_topic` | payoff · homeloan_inquiry · credit_card · deposit · complaint · other | no | UC-3 | BotEngine (participant data) |
| word_group.`usage` | intent_keywords · faq_keywords · menu_keywords · context · yes · no · yes_prefix · no_prefix · cancel · polite · filler · hesitate · dont_know · close_reason · loan_type · bank · say_as · digit_word · number_unit | no | UC-5 | BotConfig, ref qualifiers |
| phrase.`match_mode` | contains → มีคำนี้อยู่ · whole_word → ทั้งคำ (ภาษาอังกฤษ) · whole_line → ทั้งประโยคเท่านั้น · starts_with → ขึ้นต้นด้วย | no | UC-5 | BotConfig |
| faq.`action` | answer → ตอบเลย · handoff → ตอบแล้วยืนยันตัวตนและโอน | no | UC-6 | BotEngine |
| context_rule.`applies_when` | always → ทุกครั้ง · with_topic → เมื่อมีหัวข้อ/อยู่ในขั้นตอน | no | UC-9 | BotEngine |
| conversation.`channel` | genesys_voice · test | no | UC-1, UC-11 | BotEngine, list filter |
| conversation.`state` | active · handed_off · ended · expired | no | UC-12 | BotEngine, SJ-1, list filter |
| conversation.`verified_by` | ani_last4 → เบอร์ + 4 ตัวท้าย · national_id → เลขบัตร 13 หลัก | yes | UC-3 | BotEngine (identify_type) |
| test_script.`expected_action` | continue · handoff · end | yes | UC-11 | UA-1 |
| test_script.`last_status` | not_run · pass · fail | no | UC-11 | UA-1, list filter |
| customer.`segment` | mass · wealth | yes | UC-2 | BotEngine (summary) |
| deposit.`account_type` | savings → ออมทรัพย์ · fixed → ฝากประจำ · current → กระแสรายวัน | no | UC-2 | BotEngine |
| deposit.`status` / card.`status` / loan.`status` | deposit: normal/frozen/closed · card: normal/suspended/cancelled · loan: normal/closed | no | UC-2, UC-3 | BotEngine (สินเชื่อปิดแล้ว → `loan_not_active`) |
| loan.`loan_type` | home → สินเชื่อบ้าน · personal → สินเชื่อส่วนบุคคล | no | UC-2, UC-3 | BotEngine |

### 2.4 Number Config
| Key | Table | Prefix | Digits | Start | serves |
|---|---|---|---|---|---|
| `conversation-number` | conversation | `BOTC` | 7 | 1000 | UC-12 |

### 2.5 Script Includes (โค้ด: "พฤติกรรม")

| # | Key / Class | Access | Callers | Responsibility | serves |
|---|---|---|---|---|---|
| SI-1 | `si-bot-engine` / `BotEngine` | package_private | REST-1 `rest-turn`, UA-1 `ua-run-test` | ประมวลผลหนึ่ง turn: โหลด/บันทึก conversation, ลำดับการตัดสินใจ (เจ้าหน้าที่ → คำเติม → กฎบริบท → ยกเลิก → ขั้นตอนค้าง → เมนู → FAQ/intent → ไม่เข้าใจ), ยืนยันตัวตน + ล็อก, อ่านข้อมูลธนาคารและ case, ขั้นตอนคำขอสินเชื่อ, สร้าง participant data/summary/transcript | UC-1, UC-2, UC-3, UC-4, UC-11 |
| SI-2 | `si-bot-config` / `BotConfig` | package_private | SI-1, BR-3 | อ่าน config ที่ active ทั้งหมดครั้งเดียวต่อ request, ให้คะแนน intent/FAQ/menu ตามคำ, หา "คำซ้ำกับ intent อื่น" | UC-5, UC-6, UC-8, UC-9 |
| SI-3 | `si-thai-text` / `ThaiText` | package_private | SI-1, BR-3 | normalize ภาษาไทย (เลขไทย, ตัวอักษรยืด, คำลงท้าย), compact, แปลงเลขที่พูดเป็นตัวเลข, อ่านอัตรา/จำนวนเงิน/จำนวนวัน (ใช้กลุ่มคำ digit_word/number_unit) | UC-1, UC-5 |
| SI-4 | `si-renderer` / `ResponseRenderer` | package_private | SI-1, BR-4 | หา template ตาม key, แทนตัวแปร (`{P}{Q}{ME}{BRAND}{name}{amount}…`), สร้างคำอ่านออกเสียง (เลขทีละตัวเป็นกลุ่ม, บาท/สตางค์, เว้นจังหวะ, say_as), หาตัวแปรที่ไม่รู้จัก | UC-1, UC-7 |

> ไม่มี Script Include ใดเป็น clientCallable ทั้งหมดทำงานฝั่ง server

### 2.6 Scripted REST API (Genesys Data Action) — *verify at deploy: Fluent `RestApi`*

| # | Key | Definition | Detail | serves |
|---|---|---|---|---|
| REST-0 | `rest-bot-api` | Scripted REST API `Thai Bot API`, base path `/api/x_mfec3_ccbot/bot` | requires authentication; ACL REST endpoint → role `x_mfec3_ccbot.api` | UC-1 |
| REST-1 | `rest-turn` | Resource `POST /turn` | เรียก `BotEngine.turn(body)` → ตอบ 200 เสมอ (error ของบอท = handoff `adapter_error` ให้ผู้โทรไม่หลุดสาย), 400 เมื่อไม่มี `sessionId`; สัญญาตาม Section 7 | UC-1, UC-2, UC-3 |

### 2.7 Business Rules
| # | Key | Table | When | Trigger | Condition | Intent | serves |
|---|---|---|---|---|---|---|---|
| BR-1 | `br-profile-particles` | profile | before | insert, update | `voice_gender` changes | ตั้งค่าเริ่มต้น ครับ/ครับ/ผม หรือ ค่ะ/คะ/ดิฉัน (เฉพาะเมื่อผู้ใช้ไม่ได้แก้เอง) | UC-10 |
| BR-2 | `br-profile-single-active` | profile | after | insert, update | `active` changes to true | ปิด `active` ของโปรไฟล์อื่น ให้เหลือแถวเดียว | UC-10 |
| BR-3 | `br-phrase-prepare` | phrase | before | insert, update | `phrase` or `match_mode` changes | `match_key = ThaiText.compact(phrase)`; ถ้าว่างหลัง normalize → abort "คำนี้ไม่มีตัวอักษรที่ใช้เทียบได้"; ถ้า `match_key` ซ้ำใน intent_keywords ของ intent อื่น → `gs.addInfoMessage` เตือน (ไม่ abort) | UC-5 |
| BR-4 | `br-template-validate` | response_template | before | insert, update | `text` or `speech_text` changes | ถ้ามี `{xxx}` ที่ไม่อยู่ใน `placeholders` (และไม่ใช่ `{P}{Q}{ME}{BRAND}{HOTLINE}{HOURS}`) → abort พร้อมรายชื่อตัวแปรที่ใช้ได้ | UC-7 |
| BR-5a | `br-intent-name-format` | intent | before | insert, update | `name` changes | `name` ต้องตรง `^[a-z_]+$` ไม่งั้น abort | UC-9 |
| BR-5b | `br-faq-topic-format` | faq | before | insert, update | `topic` changes | `topic` ต้องตรง `^[a-z_]+$` | UC-6 |
| BR-5c | `br-context-reason-format` | context_rule | before | insert, update | `handoff_reason` changes | `handoff_reason` ต้องตรง `^[a-z_]+$` | UC-9 |
| BR-6 | `br-menu-single-main` | menu | after | insert, update | `is_main` changes to true | ปิด `is_main` ของเมนูอื่น | UC-8 |
| BR-7 | `br-menu-option-target` | menu_option | before | insert, update | `target_intent` or `target_menu` changes | ต้องมี target อย่างใดอย่างหนึ่งพอดี ไม่งั้น abort | UC-8 |
| BR-8 | `br-phone-format` | customer_phone (PoC) | before | insert, update | `phone` changes | ตัดขีด/ช่องว่าง แล้วต้องตรง `^0\d{8,9}$` ไม่งั้น abort (บอทหาลูกค้าจากเบอร์ที่โทรเข้า) | UC-2, UC-15 |
| BR-9 | `br-national-id-check` | customer (PoC) | before | insert, update | `national_id` changes | ต้องเป็นตัวเลข 13 หลักและ checksum ถูกต้อง (เหมือน `tables.valid_national_id`) ไม่งั้น abort | UC-2, UC-15 |

> ไม่มี state machine ที่ผู้ใช้เปลี่ยนสถานะเอง (Rule 11a ไม่เกี่ยว): `conversation.state` engine เป็นผู้เปลี่ยน และฟอร์มเป็น read-only

### 2.8 Client Scripts
ไม่มี (การตรวจทั้งหมดทำใน BR ฝั่ง server)

### 2.9 UI Actions
| # | Key | Table | Placement / order | Condition (visibility) | Script intent | Client | Workspace | serves |
|---|---|---|---|---|---|---|---|---|
| UA-1 | `ua-run-test` | test_script | Form button, order 100 | `!current.isNewRecord()` (role ผ่าน ACL write) | server: สร้าง session `test-<sys_id>-<เวลา>`, ส่งทุกบรรทัดของ `utterances` เข้า `BotEngine.turn` (channel=test, ani), เขียน `last_result`, ตัดสิน `last_status` จาก expected_*, `last_run_at=now`, `current.update()`, `action.setRedirectURL(current)` | no | `{ showFormButtonV2: true, isConfigurableWorkspace: true }` | UC-11 |

### 2.10 UI Policies
| # | Key | Table | Short description | Condition | Actions | serves |
|---|---|---|---|---|---|---|
| UP-1 | `up-intent-response` | intent | แสดงข้อความตอบเฉพาะ intent ที่บอทพูดข้อความ | `intent_type` IN information, conversation, urgent | `response_template`: visible + mandatory (reverseIfFalse: hidden) | UC-9 |
| UP-2 | `up-intent-builtin-lock` | intent | ล็อกชื่อและพฤติกรรมของ intent ระบบ | `builtin = true` | `name`, `intent_type`, `behavior`: readOnly | UC-9 |
| UP-3 | `up-template-builtin-lock` | response_template | ล็อก key ของข้อความระบบ | `builtin = true` | `key`: readOnly | UC-7 |

### 2.11 Roles
| Key | Name | Contains | Description | serves |
|---|---|---|---|---|
| `role-admin` | `x_mfec3_ccbot.admin` | — | ผู้ดูแลบอท (demo/PoC: role เดียว) แก้ config ทั้งหมด รันทดสอบ ดูบทสนทนา ปลดล็อก ดูแลข้อมูล PoC | UC-4–UC-12, UC-14, UC-15 |
| `role-api` | `x_mfec3_ccbot.api` | — | สำหรับ integration user ของ Genesys เท่านั้น | UC-1 |

### 2.12 ACLs (record-level; `*` = ทุกฟิลด์)
| Tables | read | write | create | delete | serves |
|---|---|---|---|---|---|
| word_group, phrase, faq, template, menu, menu_option | admin, api | admin | admin | admin; **template: เฉพาะ `builtin=false`** | UC-5–UC-8 |
| intent | admin, api | admin | admin | admin, เฉพาะ `builtin=false` | UC-9 |
| context_rule, case_state_map, profile | admin, api | admin | admin | admin | UC-9, UC-10, UC-14 |
| test_script | admin | admin | admin | admin | UC-11 |
| conversation | admin, api | api | api | api (สำหรับ SJ-1 ซึ่งรันเป็น system) | UC-1, UC-12 |
| verify_failure | admin, api | api | api | admin (ปลดล็อก), api | UC-4 |
| customer, customer_phone, deposit_account, credit_card, loan (PoC) | admin, api | admin | admin | admin | UC-2, UC-15 |
| REST endpoint `rest-bot-api` | api | — | — | — | UC-1 |

> BotEngine ใช้ `GlideRecord` (ไม่ใช่ `GlideRecordSecure`) ใน request ของ integration user แล้วตรวจสิทธิ์ของข้อมูลเองด้วยลูกค้าที่ยืนยันตัวตนแล้ว
> การอ่าน `sn_customerservice_case` ข้าม scope ต้องมี **cross-scope privilege (read)** ดู 2.19

### 2.13 Form Layouts (เรียงตามงานจริง)
| Table | Use case | Sections → fields (เรียงตามลำดับ) |
|---|---|---|
| intent | admin เพิ่ม/แก้หัวข้อ: ตั้งชื่อ → บอกว่าบอททำอะไร → ใส่คำ → ข้อมูลส่งต่อ | **Intent**: label, name, active · **Behavior**: intent_type, behavior, response_template · **Matching**: keywords, priority · **Handoff**: servicenow_topic, builtin |
| word_group | editor ดูแลกลุ่มคำ: ชื่อ/ใช้ทำอะไร → คำในกลุ่ม | **Group**: name, usage, active · **Details**: code, order, description · **Related**: Phrases (`12M` phrase.word_group) |
| phrase | editor แก้คำเดียว | **Phrase**: phrase, word_group, match_mode, active · **Advanced**: value, not_after, max_line_length, weight, match_key |
| faq | editor เพิ่มคำถาม: หัวข้อ → คำค้น → คำตอบ → ตอบหรือโอน | **FAQ**: title, topic, active · **Matching**: keywords · **Answer**: answer, action, servicenow_topic |
| response_template | editor แก้ถ้อยคำ: ดูว่าพูดตอนไหน → แก้ | **Template**: key, usage_note, placeholders · **Wording**: text, speech_text, quick_replies |
| menu | editor แก้เมนู | **Menu**: name, is_main, active · **Question**: question, opened_by · **Related**: Menu Options (`12M` menu_option.menu) |
| menu_option | editor แก้ปุ่ม | **Option**: button_label, menu, order, active · **Goes to**: target_intent, target_menu · **Matching**: answer_words |
| context_rule | admin ตั้งกฎบริบท | **Rule**: name, order, active · **When**: words, applies_when · **Then**: response_template, handoff_reason, request_note |
| case_state_map | admin แก้ถ้อยคำสถานะ | **State**: state_value, state_name · **Wording**: customer_text, is_done, is_awaiting_info |
| profile | admin ตั้งค่าบอท | **Profile**: name, active · **Voice**: voice_gender, statement_particle, question_particle, self_pronoun · **Bank**: brand_name, hotline, hours_text, agent_schedule · **Limits**: max_misunderstood, max_verify_attempts, verify_lock_attempts, verify_lock_minutes, max_case_misses, session_timeout_minutes · **Integration**: default_reply_format, handoff_field_limit, retention_days |
| test_script | editor เขียนและรันทดสอบ | **Test**: name, ani · **Lines**: utterances · **Expect**: expected_action, expected_reason, expected_text · **Result**: last_status, last_run_at, last_result |
| conversation | admin ไล่ดูสายหนึ่งสาย (read-only) | **Conversation**: session_id, channel, state, last_turn_at · **Caller**: ani, customer, verified_by · **Outcome**: handoff_reason, topics, summary · **Transcript**: transcript, misunderstood_lines · **Engine**: flow, step, context_json, turn_count |
| verify_failure | admin ปลดล็อก | **Failure**: failed_at, identity_last4, conversation, identity_hash |
| customer (PoC) | admin ดูแลลูกค้า | **Customer**: national_id, title, first_name, last_name, segment, consumer · **Related**: Phones, Deposits, Cards, Loans (`12M` ทั้ง 4 ตาราง) |
| customer_phone / deposit_account / credit_card / loan (PoC) | admin แก้รายการ | ตามลำดับฟิลด์ใน 2.2 (คีย์ → ลูกค้า → ยอด/สถานะ) |

### 2.14 List Layouts
| Table | Columns (ตามลำดับ) | Sort | serves |
|---|---|---|---|
| intent | label, name, intent_type, behavior, servicenow_topic, priority, active | priority asc | UC-9 |
| word_group | name, usage, code, order, active | usage, order | UC-5 |
| phrase | phrase, word_group, match_mode, value, active | word_group, phrase | UC-5 |
| faq | title, topic, action, servicenow_topic, active | title | UC-6 |
| response_template | key, text, builtin | key | UC-7 |
| menu | name, is_main, active | name | UC-8 |
| menu_option | menu, order, button_label, target_intent, target_menu, active | menu, order | UC-8 |
| context_rule | order, name, applies_when, handoff_reason, active | order | UC-9 |
| case_state_map | state_value, state_name, customer_text, is_done | state_value | UC-14 |
| profile | name, active, voice_gender, brand_name | name | UC-10 |
| test_script | name, last_status, last_run_at, expected_action | last_run_at desc | UC-11 |
| conversation | number, last_turn_at, state, channel, ani, customer, handoff_reason, turn_count | last_turn_at desc | UC-12 |
| verify_failure | failed_at, identity_last4, conversation | failed_at desc | UC-4 |
| customer / phone / deposit / card / loan (PoC) | คีย์, ลูกค้า, ยอด/สถานะ | คีย์ | UC-15 |

### 2.15 Application Menu & Modules
- **App Menu** `menu-app`: "Thai Call Center Bot" · roles: admin · category: Custom Applications
| Order | Module key | Title | Table / type | Roles | serves |
|---|---|---|---|---|---|
| 100 | `mod-intents` | Intents | intent list | admin | UC-9 |
| 110 | `mod-word-groups` | Word Groups | word_group list | admin | UC-5 |
| 120 | `mod-phrases` | Phrases | phrase list | admin | UC-5 |
| 130 | `mod-faq` | FAQ | faq list | admin | UC-6 |
| 140 | `mod-templates` | Responses | response_template list | admin | UC-7 |
| 150 | `mod-menus` | Menus | menu list | admin | UC-8 |
| 160 | `mod-context-rules` | Context Rules | context_rule list | admin | UC-9 |
| 170 | `mod-case-states` | Case Status Wording | case_state_map list | admin | UC-14 |
| 180 | `mod-profile` | Bot Profile | profile list | admin | UC-10 |
| 200 | `mod-tests` | Test Scripts | test_script list | admin | UC-11 |
| 300 | `mod-conversations` | Conversations | conversation list | admin | UC-12 |
| 310 | `mod-not-understood` | Not Understood | conversation list, filter `misunderstood_linesISNOTEMPTY` | admin | UC-12, UC-5 |
| 320 | `mod-verify-failures` | Verify Failures (unlock) | verify_failure list | admin | UC-4 |
| 400 | `mod-customers` | PoC Data: Customers | customer list | admin | UC-15 |
| 410 | `mod-loans` | PoC Data: Loans | loan list | admin | UC-15 |

> Menu options, phones, deposits และ cards เข้าผ่าน related list บนฟอร์มแม่ (menu/customer) จึงไม่ต้องมีโมดูลแยก

### 2.16 REST API Exposure
ไม่มีตารางที่เปิด Table API (`allowWebServiceAccess=false` ทั้งหมด) แต่มี Scripted REST 1 ตัว (2.6) ซึ่งเขียนสเปกไว้ใน Section 7 / `api-spec.md`

### 2.17 Scheduled Jobs
| Key | Name | Run | Script intent | serves |
|---|---|---|---|---|
| SJ-1 `sj-retention-purge` | Bot: purge old conversations | daily 02:30 | ลบ conversation ที่ `last_turn_at` เก่ากว่า `profile.retention_days` และ verify_failure ที่เก่ากว่า `verify_lock_minutes` ×2 (ไม่ต้องใช้แล้ว), ตั้ง `state=expired` ให้ conversation `active` ที่เกิน timeout | UC-13, UC-4 |

### 2.18 ไม่มีใน design นี้
Events, Notifications, Email Scripts, Record Producers, Defined Relationships, NowAssist skills, Flows และ Workspace ไม่มี UC ที่ต้องใช้

### 2.19 Cross-scope Privileges — *verify at deploy: Fluent cross-scope privilege record*
| Key | Target | Operation | Status | serves |
|---|---|---|---|---|
| `xscope-case-read` | table `sn_customerservice_case` (scope Customer Service) | read | allowed | UC-2 |
| `xscope-consumer-read` | table `csm_consumer` | read | allowed | UC-2 |

### 2.20 Inventory Totals
| Type | Count |
|---|---|
| Application | 1 |
| Tables | 18 (config 10 · runtime 2 · test 1 · PoC 5) |
| Fields | 146 |
| Choice fields | 21 |
| Number config | 1 |
| Script Includes | 4 |
| Scripted REST (API + resource) | 2 |
| Business Rules | 11 |
| UI Actions | 1 |
| UI Policies | 3 |
| Roles | 2 |
| ACLs | 73 (read/write/create/delete × 18 tables + REST endpoint) |
| Cross-scope privileges | 2 |
| Forms | 18 |
| Lists | 18 |
| App Menu / Modules | 1 / 15 |
| Scheduled Jobs | 1 |
| Seed data sets | 10 (ตาราง config) + PoC (ดู 5.3) |

---

## 3. Dependency Report

| Reference | From | Type | Resolution |
|---|---|---|---|
| `x_mfec3_ccbot_*` (T1–T18) | refs ภายใน | INTERNAL | สร้างใน plan |
| `cmn_schedule` | profile.agent_schedule | PLATFORM | มีใน instance (ref only) |
| `sys_user` | ACL / integration user | PLATFORM | สร้าง integration user ตอน deploy (ไม่ใช่ component) |
| `sn_customerservice_case` | BotEngine (อ่าน case ตามเลข CS… และสถานะ) | PLATFORM (CSM, Q3 ✅) | อ่านอย่างเดียว ผ่าน cross-scope privilege `xscope-case-read` (2.19) |
| `csm_consumer` | customer.consumer; BotEngine เทียบ `case.consumer` | PLATFORM (CSM, Q3 ✅) | reference + cross-scope privilege `xscope-consumer-read` |
| ตารางข้อมูลธนาคารเดิมของ instance | — | ไม่ใช้ในรอบนี้ (Q2) | ใช้ T14–T18 (INTERNAL) ไปก่อน |
| Genesys Cloud Data Action | ภายนอก | EXTERNAL (ไม่ใช่ component) | แก้ URL + auth ของ Data Action เดิม |

- ไม่มี reference แบบ mandatory ที่วนกันเป็นวง (cycle)
- reference ระหว่าง config (intent → word_group, menu_option → menu/intent) ใช้ cascade `restrict` ป้องกันการลบสิ่งที่ยังถูกใช้อยู่

---

## 4. Validation Report (revision 2: หลังตอบ Q1–Q7)

### 4A Traceability: ✅ PASSED
**Forward (UC → components)**
| UC | Components |
|---|---|
| UC-1 | REST-0/1, SI-1–4, T2, T11, profile (session_timeout_minutes, default_reply_format), role-api, ACL api |
| UC-2 | SI-1, T14–T18, BR-8, BR-9, T10, T11.customer/verified_by, xscope-case-read, xscope-consumer-read, REST-1 |
| UC-3 | SI-1, T2.servicenow_topic, T9, T5.action, T11 (summary, transcript, handoff_reason), profile (agent_schedule, handoff_field_limit) |
| UC-4 | T12, SI-1, profile verify_*, mod-verify-failures, SJ-1, ACL delete (admin) |
| UC-5 | T3, T4, BR-3, SI-2, SI-3, mod-word-groups, mod-phrases |
| UC-6 | T5, BR-5b, mod-faq |
| UC-7 | T6, BR-4, SI-4, UP-3, mod-templates |
| UC-8 | T7, T8, BR-6, BR-7, mod-menus |
| UC-9 | T2, T9, BR-5a, BR-5c, UP-1, UP-2, mod-intents, mod-context-rules |
| UC-10 | T1, BR-1, BR-2, mod-profile |
| UC-11 | T13, UA-1, SI-1, mod-tests |
| UC-12 ⚠️ Q8 | T11 (number, misunderstood_lines, transcript), conversation-number, mod-conversations, mod-not-understood |
| UC-13 | SJ-1, profile.retention_days (30) |
| UC-14 | T10, mod-case-states |
| UC-15 | T14–T18 forms/lists, BR-8, BR-9, mod-customers, mod-loans |

**Reverse:** ทุก component ใน Section 2 มี `serves:` ที่ไม่ว่าง ✅
**A4:** ไม่มี component ที่อ้างแค่ "best practice" ✅
UC-12 รอการตัดสินจาก Q8 ถ้าตัด ให้ลบ component ในแถว UC-12 ที่ไม่ได้ serve UC อื่น

### 4B Feasibility: ✅ PASSED (มีรายการ verify at deploy)
| # | ผล | หมายเหตุ |
|---|---|---|
| B1 | ✅ | ไม่มี Flow/Subflow/Workspace |
| B2 | ✅ | ไม่ extend OOTB (CSM อ่านอย่างเดียว), ไม่มี `u_`, ชื่อตาราง ≤ 30 ตัวอักษร |
| B3 | ✅ | ทุก type อยู่ใน mapping; `currency`→Decimal; `multiline`→String(4000); `phone_safe`→String + regex ใน BR-8 |
| B3a | ✅ | ทุกฟิลด์ที่มีค่าตายตัวเป็น choice; ทุก reference ระบุ cascade |
| B4 | ⚠️ verify | (1) Scripted REST ผ่าน Fluent `RestApi` (2) cross-scope privilege ผ่าน Fluent (3) `GlideDigest` SHA-256 ใน scoped app (4) release และ JavaScript mode ของ scope (Q4) (5) OAuth client credentials grant ใน release นั้น (6) ความเร็ว: โหลด config ~2,000 แถวต่อ turn ควร < 300 ms |
| B5 | ✅ | ใช้ `cmn_schedule`, auto-number, ACL และ OAuth ของ platform แทนการเขียนเอง |
| B6 | ✅ n/a | ไม่มี NowAssist |

### 4C Cross-Reference & Orphans: ✅ PASSED
| # | ผล | หมายเหตุ |
|---|---|---|
| C1–C5 | ✅ n/a | ไม่มี email script/event/notification |
| C6 | ✅ | admin → ACL + app menu + modules; api → ACL + REST endpoint |
| C7 | ✅ | SI-1 ← REST-1, UA-1 · SI-2 ← SI-1, BR-3 · SI-3 ← SI-1, BR-3 · SI-4 ← SI-1, BR-4 |
| C8 | ✅ n/a | ไม่มี REL list |
| C9 | ✅ | ไม่เหลือ UNKNOWN: CSM = PLATFORM, ข้อมูลธนาคาร = INTERNAL (PoC) |

**Binding Table:** ไม่มี email script

### 4D Completeness: ✅ PASSED
| # | ผล | หมายเหตุ |
|---|---|---|
| D1 | ✅ | ทุก reference มีปลายทาง (INTERNAL/PLATFORM) |
| D2 | ✅ | ทุก choice มี ≥2 ค่า, ฟิลด์ mandatory ไม่มี none, `behavior` dependent_on `intent_type` |
| D3 | ✅ | ทุกตารางมีฟิลด์ และทุกฟิลด์มี serves |
| D4 | ✅ | display column ตารางละหนึ่ง |
| D5 | ✅ | BR ที่ทำงานตอน update มี condition |
| D6 | ✅ n/a | ไม่มี client script |
| D7 | ✅ | ทุก ACL มี role |
| D8 | ✅ | `x_mfec3_ccbot.admin`, `x_mfec3_ccbot.api` |
| D9 | ✅ | scope `x_mfec3_ccbot` |
| D10 | ✅ | ไม่มีตารางผ่าน Table API |
| D11 | ✅ | form/list ทุกตัวมี use case |
| D12 | ✅ | App Menu 1 + modules |
| D14–D16 | ✅ n/a | ไม่มี relationship/notification; SJ-1 เป็น daily + run_time |
| D17 | ✅ n/a | ไม่มีการเปลี่ยนสถานะโดยผู้ใช้ |
| D18 | ✅ | UA-1 มี script intent, order และ workspace |
| D19 | ✅ | SI ทุกตัวมี ≥ 2 caller |

### 4E Deployment Readiness: ✅ PASSED
| # | ผล | หมายเหตุ |
|---|---|---|
| E1 | ✅ | key ไม่ซ้ำ ไม่มี sys_id |
| E2–E3 | ✅ | depends_on ทุกตัวมีอยู่จริง และลำดับใน 5.2 ไม่วน |
| E4 | ✅ | ทุก reference เป็น INTERNAL หรือ PLATFORM |
| E5 | ✅ | ยอดใน 5.4 ตรงกับ 2.20 |
| E6 | ✅ | ไม่มี path `.now.ts` ไม่มี credential |

**Overall: ✅ ผ่านทั้ง 5 gate** เหลือแค่ตัดสิน Q8 (ขอบเขต ไม่ใช่ข้อผิดพลาด) และรายการ verify at deploy ใน 4B

---

## 5. Build Plan (Approval: **PENDING** — รอ "APPROVED" และคำตอบ Q8)

### 5.1 Component spec index
props ของตารางและฟิลด์อยู่ใน 2.2, choices ใน 2.3, ACL ใน 2.12, form/list ใน 2.13–2.14 โดย deploy ใช้ key ตามนี้

| Key | Type | Table | References | depends_on |
|---|---|---|---|---|
| `app` | Application | n/a | scope `x_mfec3_ccbot` | — |
| `role-admin`, `role-api` | Role | n/a | — | app |
| `word-group-table` | Table + fields | `x_mfec3_ccbot_word_group` | — | app |
| `template-table` | Table + fields | `x_mfec3_ccbot_template` | — | app |
| `profile-table` | Table + fields | `x_mfec3_ccbot_profile` | agent_schedule → PLATFORM `cmn_schedule` | app |
| `intent-table` | Table + fields | `x_mfec3_ccbot_intent` | keywords → word-group-table; response_template → template-table | word-group-table, template-table |
| `phrase-table` | Table + fields | `x_mfec3_ccbot_phrase` | word_group → word-group-table | word-group-table |
| `faq-table` | Table + fields | `x_mfec3_ccbot_faq` | keywords → word-group-table | word-group-table |
| `menu-table` | Table + fields | `x_mfec3_ccbot_menu` | opened_by → word-group-table | word-group-table |
| `menu-option-table` | Table + fields | `x_mfec3_ccbot_menu_option` | menu → menu-table; answer_words → word-group-table; target_intent → intent-table; target_menu → menu-table | menu-table, intent-table |
| `context-rule-table` | Table + fields | `x_mfec3_ccbot_context_rule` | words → word-group-table; response_template → template-table | word-group-table, template-table |
| `case-state-table` | Table + fields | `x_mfec3_ccbot_case_state_map` | — | app |
| `customer-table` | Table + fields | `x_mfec3_ccbot_customer` | consumer → PLATFORM `csm_consumer` | app |
| `customer-phone-table`, `deposit-table`, `card-table`, `loan-table` | Table + fields | `x_mfec3_ccbot_customer_phone`, `_deposit_account`, `_credit_card`, `_loan` | customer → customer-table | customer-table |
| `conversation-table` | Table + fields | `x_mfec3_ccbot_conversation` | customer → customer-table | customer-table |
| `verify-failure-table` | Table + fields | `x_mfec3_ccbot_verify_failure` | conversation → conversation-table | conversation-table |
| `test-script-table` | Table + fields | `x_mfec3_ccbot_test_script` | — | app |
| `choices-*` (21 fields) | Choice | ตาม 2.3 | `behavior` dependent_on `intent_type` | tables |
| `conversation-number` | NumberConfig | conversation | prefix BOTC, 7 digits, start 1000 | conversation-table |
| `form-*`, `list-*` (18 + 18) | FormSection/FormElement/ListColumn | ตาม 2.13–2.14 | related lists 12M: phrase.word_group, menu_option.menu, 4 PoC ตาราง .customer | tables, fields |
| `up-intent-response`, `up-intent-builtin-lock`, `up-template-builtin-lock` | UiPolicy + actions | intent, template | — | intent-table, template-table |
| `br-profile-particles`, `br-profile-single-active` | BusinessRule | profile | — | profile-table |
| `br-phrase-prepare` | BusinessRule | phrase | SI `ThaiText`, `BotConfig` | phrase-table, si-thai-text, si-bot-config |
| `br-template-validate` | BusinessRule | template | SI `ResponseRenderer` | template-table, si-renderer |
| `br-intent-name-format`, `br-faq-topic-format`, `br-context-reason-format` | BusinessRule | intent, faq, context_rule | — | tables |
| `br-menu-single-main`, `br-menu-option-target` | BusinessRule | menu, menu_option | — | menu-table, menu-option-table |
| `br-phone-format`, `br-national-id-check` | BusinessRule | customer_phone, customer | — | PoC tables |
| `si-thai-text` | ScriptInclude | n/a | word_group (digit_word, number_unit, polite) | word-group-table, phrase-table |
| `si-renderer` | ScriptInclude | n/a | template-table, profile-table, word_group say_as | template-table, profile-table |
| `si-bot-config` | ScriptInclude | n/a | config tables T1–T10 | config tables, si-thai-text |
| `si-bot-engine` | ScriptInclude | n/a | SI-2/3/4; T11–T18; PLATFORM `sn_customerservice_case` | all tables, si-bot-config, si-renderer, xscope-* |
| `xscope-case-read`, `xscope-consumer-read` | CrossScopePrivilege (verify) | PLATFORM tables | read | app |
| `rest-bot-api` | ScriptedRestApi (verify) | n/a | role-api | app, role-api |
| `rest-turn` | ScriptedRestResource (verify) | n/a | si-bot-engine | rest-bot-api, si-bot-engine |
| `ua-run-test` | UiAction | test_script | si-bot-engine | test-script-table, si-bot-engine |
| `acl-*` (73) | Acl + AclRole | ตาม 2.12 | role-admin, role-api | tables, roles |
| `sj-retention-purge` | ScheduledJob (daily 02:30) | n/a | profile, conversation, verify_failure | tables |
| `menu-app` | AppMenu | n/a | role-admin | app, role-admin |
| `mod-*` (15) | AppModule | ตาม 2.15 | menu-app | menu-app, tables |
| `seed-*` | Seed data | config + PoC tables | ตาม 5.3 | all of the above |

ตัวอย่าง spec แบบเต็ม (รูปแบบที่ส่งให้ servicenow-deploy):
```
- key:        si-bot-engine
  type:       ScriptInclude
  table:      n/a
  serves:     UC-1, UC-2, UC-3, UC-4, UC-11
  props:      apiName x_mfec3_ccbot.BotEngine, accessibleFrom package_private, clientCallable false
              public method: turn({sessionId, text, ani, format, channel}) → response object (api-spec.md)
  references: si-bot-config, si-thai-text, si-renderer (INTERNAL); T1–T18 (INTERNAL);
              sn_customerservice_case, csm_consumer (PLATFORM, via xscope-*)
  depends_on: si-bot-config, si-thai-text, si-renderer, xscope-case-read, xscope-consumer-read, all tables

- key:        rest-turn
  type:       ScriptedRestResource   (verify at deploy: Fluent RestApi)
  table:      n/a
  serves:     UC-1, UC-2, UC-3
  props:      api rest-bot-api, method POST, path /turn, requiresAuthentication true,
              acl role x_mfec3_ccbot.api, script: parse JSON → BotEngine.turn → 200 JSON (400 if no sessionId)
  references: si-bot-engine (INTERNAL), role-api (INTERNAL)
  depends_on: rest-bot-api, si-bot-engine, role-api
```

### 5.2 Deploy order
1. Application (scope `x_mfec3_ccbot`) — ตรวจ release/JS mode ก่อน (Q4)
2. Roles (admin, api)
3. Tables + fields: word_group, template → profile, intent, phrase, faq, menu, menu_option, context_rule, case_state_map → customer → customer_phone, deposit_account, credit_card, loan → conversation → verify_failure, test_script
4. Choices → Number config (BOTC)
5. Form sections/elements (related lists 12M) → List columns
6. UI Policies (UP-1–3)
7. Script Includes: ThaiText → ResponseRenderer → BotConfig → BotEngine
8. Business Rules (BR-1 … BR-9)
9. Cross-scope privileges (case, consumer read)
10. Scripted REST API + resource `/turn`
11. UI Action `ua-run-test`
12. ACLs + ACL roles (รวม REST endpoint)
13. Scheduled Job SJ-1
14. App Menu + Modules
15. Seed data (5.3) → รัน test_script ทั้งหมด → ต้อง pass ก่อนเปิดให้ Genesys เรียก
16. ตั้งค่า platform หลัง deploy: integration user + OAuth (checklist ใน `api-spec.md`) → แก้ Data Action ของ Genesys

### 5.3 Seed data (ย้าย config เดิม, สร้างอัตโนมัติจากโค้ด Python ที่ `23eb025`)
| Target | มาจาก | จำนวนโดยประมาณ |
|---|---|---|
| intent + word_group(intent_keywords) + phrase | `intents.KEYWORDS`, `bot.REQUESTS`, `URGENT`, `TOPIC_NAMES`, `transcripts.topic()` | 22 intent · 277 คำ |
| word_group พิเศษ + phrase | `CANCEL_WORDS`, `YES/NO(_PREFIXES)`, `POLITE`, `FILLERS`, `HESITATE`, `DONT_KNOW`, `LOAN_TYPES`, `CLOSE_REASONS`(+`REASON_CODES`→code), `offers.BANKS`, `offers.DIGITS/UNITS`, `normalize.DIGIT_WORDS`, `config.SAY_AS` | ~20 กลุ่ม · ~250 คำ |
| context_rule | `DECEASED`, `ON_BEHALF` | 2 กฎ |
| faq + word_group(faq_keywords) | `seed_faq.sql` | 46 ข้อ |
| response_template | ข้อความภาษาไทยใน `bot.py` (~484 literal รวมคำในรายการ) | ~150 template (ส่วนที่เหลือเป็นกลุ่มคำ) |
| menu + menu_option + word_group(menu_keywords) | `config.MAIN_MENU`, `CATEGORIES`, `MENU_CHOICES`, `LOAN/CLOSE/AMOUNT_MENU` | 7 เมนู · ~35 ตัวเลือก |
| case_state_map | `config.CASE_STATES`, `CASE_DONE_STATES`, `CASE_AWAITING_INFO` | 6 แถว |
| profile | `config.py` | 1 แถว |
| test_script | ชุดสนทนาจาก `tests/test_bot.py`, `test_phrasings.py` | เลือก ~30 สคริปต์หลัก |
| PoC data (Q2) | `seed.sql` (รวม C1–C5 PayOff) ลูกค้า PoC ผูก `consumer` กับ csm_consumer ที่มีชื่อตรงกัน ถ้ามี | ตามข้อมูลเดิม |

> วิธี seed (ข้อมูลใน Fluent หรือ import XML) จะเลือกตอน deploy เป้าหมายคือ engine ใหม่ต้องให้ผลเหมือน engine Python กับ test_script ชุดเดียวกัน (UC-11)

### 5.4 Summary
```
Build Plan
  App / Scope: Thai Call Center Bot / x_mfec3_ccbot
  Schema:   tables 18  fields 146
  Config:   roles 2  choice-fields 21  number 1  relationships 0  forms 18  lists 18
            ui-policies 3  BRs 11  client-scripts 0  script-includes 4  ui-actions 1  acls 73
            scripted-rest 2 (verify at deploy)  cross-scope 2  email-scripts 0  events 0  notifications 0  scheduled-jobs 1
            app-menu 1  app-modules 15  catalog-items 0  nowassist-skills 0
  Seed:     config 10 tables (~2,000 rows) + PoC bank data
  Deployed by: Fluent SDK (@servicenow/sdk) — Node.js 20+, @servicenow/sdk 4.6+
  REST spec: api-spec.md (Scripted REST /turn; no Table API exposure)
```

### 5.5 Approval gate
```
⚠️  ตอบ Q8 (เก็บหรือตัดหน้าดูบทสนทนาย้อนหลัง) แล้วพิมพ์ "APPROVED" เพื่อส่งต่อให้ servicenow-deploy
    จากนั้นต้องมี instance + credential สำหรับ deploy ด้วย Fluent SDK หรือบอกส่วนที่อยากแก้ได้
```

---

## 6. Deployment Status
NOT STARTED

---

## 7. REST API Spec
ดู `api-spec.md` (Scripted REST `POST /api/x_mfec3_ccbot/bot/turn` ซึ่งเป็นสัญญาเดียวกับ Data Action เดิมของ Genesys)
