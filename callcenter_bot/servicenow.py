"""Cases in a real ServiceNow instance, through the Table API, instead of the local mock table.

Turned on by setting, on the server:

    SERVICENOW_INSTANCE=https://yourcompany.service-now.com
    SERVICENOW_USER=<integration user>        # needs read/create on sn_customerservice_case
    SERVICENOW_PASSWORD=<password>

The bot then opens and reads cases in [sn_customerservice_case] with the same fields as the local
table (callcenter_bot/data/schema.sql), so nothing else changes.

    open a case    POST /api/now/table/sn_customerservice_case
    read a case    GET  /api/now/table/sn_customerservice_case?sysparm_query=number=CS0001001

NOT YET TRIED ON A REAL INSTANCE. Things that depend on how your instance is set up:
- `consumer` is a reference: ServiceNow wants the consumer record's sys_id, not a phone number.
  Until customers also come from ServiceNow, the phone goes into the description instead.
- callback_phone and order_id have no standard field. Name your custom fields in
  SERVICENOW_FIELD_MAP (e.g. "callback_phone=u_callback_phone,order_id=u_order_number");
  without it they are written into the description.
- category and contact_type are choice fields: their values must exist in your choice lists, or
  map them with SERVICENOW_FIELD_MAP / leave them out with SERVICENOW_SKIP_FIELDS=category.
- Basic authentication. For OAuth, replace _headers().
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TABLE = "sn_customerservice_case"
READ_FIELDS = "sys_id,number,state,short_description,category,opened_at,close_notes,order_id"


class CaseError(RuntimeError):
    """ServiceNow could not be reached or refused the request: the bot hands over to a person."""


def configured() -> bool:
    return bool(os.environ.get("SERVICENOW_INSTANCE"))


def _setting(name, default=""):
    return os.environ.get(name, default).strip()


def _field_map() -> dict:
    pairs = (p.split("=", 1) for p in _setting("SERVICENOW_FIELD_MAP").split(",") if "=" in p)
    return {ours.strip(): theirs.strip() for ours, theirs in pairs}


def _headers() -> dict:
    token = base64.b64encode(f"{_setting('SERVICENOW_USER')}:{_setting('SERVICENOW_PASSWORD')}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json", "Content-Type": "application/json"}


def _call(method: str, query: dict = None, body: dict = None) -> dict:
    url = f"{_setting('SERVICENOW_INSTANCE').rstrip('/')}/api/now/table/{TABLE}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=_headers())
    timeout = float(_setting("SERVICENOW_TIMEOUT", "8"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise CaseError(f"ServiceNow answered {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise CaseError(f"ServiceNow not reachable: {e}") from e


def create_case(fields: dict) -> str:
    """Open a case from the local field names; returns its number (CS...)."""
    mapping, skip = _field_map(), {f.strip() for f in _setting("SERVICENOW_SKIP_FIELDS").split(",") if f.strip()}
    body, extra = {}, []
    labels = {"consumer": "เบอร์ลูกค้า (ยืนยันตัวตนแล้ว)", "callback_phone": "เบอร์ติดต่อกลับ", "order_id": "เลขคำสั่งซื้อ"}
    for name, value in fields.items():
        if value in (None, "") or name in skip:
            continue
        if name in mapping:
            body[mapping[name]] = value
        elif name in labels:                       # no standard field: keep it in the description
            extra.append(f"{labels[name]}: {value}")
        else:
            body[name] = value
    if extra:
        body["description"] = "\n".join(filter(None, [body.get("description"), *extra]))
    result = _call("POST", {"sysparm_fields": "sys_id,number"}, body).get("result") or {}
    if not result.get("number"):
        raise CaseError("ServiceNow did not return a case number")
    return result["number"]


def get_case(number: str):
    """The case with this number as {number, state, opened_at, category, close_notes, order_id}, or None."""
    mapping = _field_map()
    order_field = mapping.get("order_id", "order_id")
    rows = _call("GET", {"sysparm_query": f"number={number}", "sysparm_limit": "1",
                         "sysparm_fields": READ_FIELDS.replace("order_id", order_field)}).get("result") or []
    if not rows:
        return None
    row = rows[0]
    try:
        state = int(row.get("state") or 0)
    except ValueError:
        state = 0
    return {"number": row.get("number"), "state": state, "opened_at": row.get("opened_at") or None,
            "category": row.get("category") or None, "close_notes": row.get("close_notes") or None,
            "order_id": row.get(order_field) or None}
