# Thai Call Center Bot — REST API Spec

> เอกสารประกอบ `design.md` Section 7 (เอกสารเท่านั้น ไม่มี endpoint ที่เปิดใช้งานจริง และไม่มี credential)
> สัญญาเหมือน `POST /api/genesys/turn` ของบอท Python ที่ commit `23eb025` ทุกฟิลด์
> Genesys Data Action "Thai Bot Turn" (`channels/genesys/data-action.json`) จึงแก้แค่ URL และ auth

## Table API
ไม่มีตารางที่เปิด Table API (`allowWebServiceAccess = false` ทุกตาราง)
config และข้อมูลแก้ผ่าน UI ของ ServiceNow ตาม role

## ตั้งค่าหลัง deploy (platform ไม่ใช่ component ของ app)

**ServiceNow**
1. สร้าง user `genesys.thai_bot` (Web service access only) แล้วให้แค่ role `x_mfec3_ccbot.api`
2. เปิด client credentials grant ของ OAuth ตามที่ release รองรับ (servicenow-deploy ตรวจชื่อ property และเวอร์ชันให้ตอน deploy, Q4)
3. System OAuth → Application Registry → **Create an OAuth API endpoint for external clients**:
   ตั้งชื่อ `Genesys Thai Bot`, ผูก user ในข้อ 1 สำหรับ client credentials แล้วเก็บ Client ID/Secret ไว้
4. ทดสอบขอ token:
   ```bash
   curl -s -X POST https://<instance>.service-now.com/oauth_token.do \
     -d grant_type=client_credentials -d client_id=<id> -d client_secret=<secret>
   ```

**Genesys Cloud**
5. Integrations → Web Services Data Actions (ตัวใหม่สำหรับ ServiceNow) → Credentials ชนิด **User Defined (OAuth)**:
   ใส่ client id/secret และขอ token จาก `oauth_token.do` ด้วย grant client credentials
6. Data Action "Thai Bot Turn": Request URL → `https://<instance>.service-now.com/api/x_mfec3_ccbot/bot/turn`
   แล้วลบ header `x-bot-secret` (ใช้ OAuth แทน) โดย input/output contract เหมือนเดิม
7. ทดสอบใน Data Action "Test" ด้วย `{"sessionId":"test-1","text":"","ani":"+66810000002"}` ต้องได้คำทักทาย

> ชื่อเมนูและชนิด credential ใน Genesys/ServiceNow อาจต่างไปตาม release ให้ยึดหน้าจอจริง

## Scripted REST: Thai Bot API — `POST /api/x_mfec3_ccbot/bot/turn`

| | |
|---|---|
| Base | `https://<instance>.service-now.com/api/x_mfec3_ccbot/bot` |
| Resource | `POST /turn` |
| Auth | **OAuth 2.0 client credentials** (Q7): `Authorization: Bearer <access_token>` จาก `POST https://<instance>.service-now.com/oauth_token.do` token ทำงานในนามของ integration user ที่มีแค่ role `x_mfec3_ccbot.api` ผู้เรียกเป็นคนเก็บ client secret ไม่เก็บไว้ที่นี่ |
| Content-Type | `application/json; charset=utf-8` |
| เรียกเมื่อ | ทุก turn ของ Genesys voice Bot Flow (Call Data Action) |

### Request body
| Field | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string (≤256) | ✓ | `Session.ConversationId` = หนึ่งบทสนทนาต่อสาย |
| `text` | string (≤1000) | | สิ่งที่ผู้โทรพูด; ว่างใน turn แรก (บอททักทาย) |
| `ani` | string | | `Call.Ani` เบอร์ที่โทรเข้า (ใช้ยืนยันตัวตนด้วยเลขบัตร 4 ตัวท้าย ถ้าเป็นเบอร์ที่ลงทะเบียน) |
| `format` | `speech` \| `text` | | ว่าง = `profile.default_reply_format` |

### Response (HTTP 200, ทุกค่าเป็น string แบบ flat)
| Field | Description |
|---|---|
| `reply` | สิ่งที่ให้ Genesys พูด (คำอ่านออกเสียงเมื่อ format=speech) |
| `action` | `continue` \| `handoff` \| `end` |
| `handoffReason` | เหตุผลที่โอน: `name` ของ intent, `topic` ของ FAQ, `handoff_reason` ของ context rule หรือค่าระบบ (`agent`, `verify_failed`, `verify_locked`, `adapter_error`) |
| `verifiedPhone` | เบอร์ที่ลงทะเบียนของลูกค้าที่ยืนยันแล้ว (+66…) หรือว่าง |
| `expectsDigits` | `true` ระหว่างรอตัวเลข |
| `customerName` | ชื่อลูกค้าที่ยืนยันแล้ว |
| `requestDetail` | ลูกค้าต้องการอะไร |
| `ticket` | เลข case ที่คุยถึง (ของลูกค้าเอง) |
| `loanDetail` | สินเชื่อที่คำขอพูดถึง |
| `closeReason` | เหตุผลปิดสินเชื่อ (ข้อความ) |
| `summary` | สรุปหนึ่งบรรทัดสำหรับเจ้าหน้าที่ (≤ `profile.handoff_field_limit`) |
| `transcript` | ท้ายบทสนทนา (≤ `profile.handoff_field_limit`) |
| `topic` | `payoff` \| `homeloan_inquiry` \| `credit_card` \| `deposit` \| `complaint` \| `other` (จาก `servicenow_topic`) |
| `identify_type` | `national_id` เมื่อยืนยันแล้ว ไม่งั้นว่าง |
| `kyc_result` | `pass` \| `fail` \| ว่าง |
| `loan_number` | เช่น `PHL-LN-0002` |
| `reason` | `refinance` \| `own_funds` \| `sell_property` \| `high_installment` \| `high_interest` \| `not_given` \| `other` (จาก `word_group.code`) |
| `closing_within_days` | เช่น `30` |
| `new_bank_name` | จาก `phrase.value` ของกลุ่ม `bank` |
| `new_interest_rate` | % ต่อปี |
| `promotion_period_months` | เดือน |
| `cashback_offered` | บาท |

**Errors**
- `400 {"error": "sessionId is required"}`: ไม่มี sessionId
- `401/403`: auth หรือ role ไม่ถูกต้อง (มาจาก platform)
- ทุก error อื่นของบอท → **200** `action=handoff`, `handoffReason=adapter_error` พร้อมคำขอโทษ ผู้โทรจะได้ไม่หลุดสาย

### Example (คำตอบจริงจากบอท Python ที่ `23eb025`)
```http
POST /api/x_mfec3_ccbot/bot/turn
Content-Type: application/json

{"sessionId": "6f1c…", "text": "อยากปิดบัญชีสินเชื่อบ้านครับ", "ani": "+66810000002"}
```
```json
{"reply": "ต้องการปิดบัญชีสินเชื่อบ้าน, ใช่ไหมครับ", "action": "continue", "handoffReason": "",
 "verifiedPhone": "", "expectsDigits": "false", "customerName": "", "requestDetail": "", "ticket": "",
 "loanDetail": "", "closeReason": "", "summary": "", "transcript": "", "topic": "", "identify_type": "",
 "kyc_result": "", "loan_number": "", "reason": "", "closing_within_days": "", "new_bank_name": "",
 "new_interest_rate": "", "promotion_period_months": "", "cashback_offered": ""}
```
