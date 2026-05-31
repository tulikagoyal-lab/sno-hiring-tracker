"""
SNO Hiring Cost Tracker - FastAPI Backend with HTML UI
Replaces the Streamlit frontend; all business logic preserved.
"""

import hashlib
import json
import logging
import os
import secrets
import warnings
from datetime import datetime, timedelta
from functools import lru_cache
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO)

# Config
SF_ACCOUNT = os.environ.get("SNOWFLAKE_ACCOUNT", "GZAVXAB-SWIGGY_MUMBAI")
SF_WAREHOUSE = os.environ.get("SNOWFLAKE_WAREHOUSE", "NONTECH_WH_01")
SF_ROLE = os.environ.get("SNOWFLAKE_ROLE", "DRIVERS_ORG")
SF_USER = os.environ.get("SNOWFLAKE_USER", "")
SF_PRIVATE_KEY = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "")
SF_ACCESS_TOKEN = os.environ.get("SNOWFLAKE_ACCESS_TOKEN", "")
GCP_SA_FILE = os.environ.get("GCP_SERVICE_ACCOUNT_FILE", "")
GCP_SA_JSON = os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "")
SHEET_ID = os.environ.get("SHEET_ID", "116n7chDnpyh14Z4TTL7jEBRG1XoYDGzE_O01JCI6iPc")
SHEET_GID = os.environ.get("SHEET_GID", "37744413")
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", "86400"))

# Pydantic Models
class LoginRequest(BaseModel):
    name: str
    passcode: str

class SubmissionRequest(BaseModel):
    week_label: str
    metrics: dict[str, float]

# Channel Definitions (from original app.py)
CHANNELS = {
    "SNO Channel": {
        "passcode": "sno123",
        "sections": {
            "Orders (SNO)": ["orders_sno"],
            "SNO Hiring": ["sno_spillover_28","sno_cpfod_ref","sno_cpfod_rb_override","sno_cpfod_agency","sno_rejoiner"],
            "SNO Absolute Cost": [
                "cost_flatpay","cost_leakage","cost_shouldering","cost_dormant_rb",
                "cost_impersonation","cost_jb","cost_rb_cpfod","cost_rb_fod",
                "cost_ref_override_cpfod","cost_ref_override_fod","cost_spillover_28",
                "cost_agency","cost_google_supper","cost_google_extra","cost_google_fresh_fod",
                "cost_google_im_app","cost_google_im_1st","cost_google_extra_1st",
                "cost_upfront_fee","cost_insurance","cost_ob_fee",
                "cost_apsflyer","cost_pivot_roots","cost_autodialer",
                "cost_bgv_fresh","cost_bgv_address","cost_bgv_rejoiner",
                "cost_sms_fresh","cost_sms_rejoiner",
                "cost_whatsapp_fresh","cost_whatsapp_rejoiner",
                "cost_obe_rtc","cost_fr_salary","cost_fr_count",
                "cost_fr_tl_salary","cost_fr_tl_count","cost_btl",
                "cost_fr_incentive","cost_influencer_payout",
                "cost_inf_tl_salary","cost_inf_tl_count",
                "cost_spillover_over_28","cost_other_mult","cost_other_val",
            ],
            "SNO Same Week Transacting": ["transact_ref","transact_google","transact_affiliate","transact_ssu","transact_fr","transact_agency","transact_influencers"],
            "SNO Spill Over FOD": ["spill_fod_ref","spill_fod_google","spill_fod_affiliate","spill_fod_ssu","spill_fod_fr","spill_fod_agency","spill_fod_influencers"],
            "SNO Onboarding": ["onboard_ref","onboard_google","onboard_affiliate","onboard_ssu","onboard_fr","onboard_agency","onboard_influencers"],
        }
    },
    "SOC Channel": {
        "passcode": "soc123",
        "sections": {
            "Orders (SOC)": ["orders_soc"],
            "SOC Hiring": ["soc_fresh_onboard","soc_rejoiner","soc_spillover_28","soc_spillover_over_28"],
            "SOC CPH": ["soc_cpod_ref"],
            "SOC Absolute Cost": [
                "soc_rejoiner_cost","soc_jb_cost","soc_rb_cpfod","soc_cost_spillover_28",
                "soc_cost_spillover_over_28","soc_jb_adjust","soc_rb_adjust",
                "soc_agency_cost","soc_google_im","soc_google_supper",
                "soc_google_im_sa_fod","soc_google_sf_sa_fod","soc_extra_im",
                "soc_upfront_fee","soc_insurance","soc_ob_fee","soc_ob_fees_actual",
                "soc_bgv","soc_sms_fresh","soc_sms_rejoiner",
                "soc_whatsapp_fresh","soc_whatsapp_rejoiner",
                "soc_btl","soc_tc_incentive","soc_fr_count","soc_tl_count",
                "soc_fr_initiatives","soc_fr_extra",
            ],
            "SOC Same Week Transacting": ["soc_transact_ref","soc_transact_google","soc_transact_affiliate","soc_transact_ssu","soc_transact_fr","soc_transact_agency","soc_transact_goldmine","soc_transact_influencers"],
            "SOC Spill Over FOD": ["soc_spill_fod_ref","soc_spill_fod_google","soc_spill_fod_affiliate","soc_spill_fod_ssu","soc_spill_fod_fr","soc_spill_fod_agency","soc_spill_fod_influencers"],
        }
    },
    "Agency Channel": {
        "passcode": "agency123",
        "sections": {
            "SNO Agency Cost": ["cost_agency"],
            "SNO Agency Transacting": ["transact_agency"],
            "SNO Agency Spillover": ["spill_fod_agency"],
            "SNO Agency Onboarding": ["onboard_agency"],
            "SOC Agency Cost": ["soc_agency_cost"],
            "SOC Agency Transacting": ["soc_transact_agency"],
            "SOC Agency Spillover": ["soc_spill_fod_agency"],
        }
    },
    "Google Channel": {
        "passcode": "google123",
        "sections": {
            "SNO Google Costs": ["cost_google_supper","cost_google_extra","cost_google_fresh_fod","cost_google_im_app","cost_google_im_1st","cost_google_extra_1st"],
            "SNO Google Transacting": ["transact_google"],
            "SNO Google Spillover": ["spill_fod_google"],
            "SNO Google Onboarding": ["onboard_google"],
            "SOC Google Costs": ["soc_google_im","soc_google_supper","soc_google_im_sa_fod","soc_google_sf_sa_fod","soc_extra_im"],
            "SOC Google Transacting": ["soc_transact_google"],
            "SOC Google Spillover": ["soc_spill_fod_google"],
        }
    },
    "Referral Channel": {
        "passcode": "ref123",
        "sections": {
            "SNO Referral CPFOD": ["sno_cpfod_ref","sno_cpfod_rb_override"],
            "SNO Referral Cost": ["cost_rb_cpfod","cost_rb_fod","cost_ref_override_cpfod","cost_ref_override_fod"],
            "SNO Referral Transacting": ["transact_ref"],
            "SNO Referral Spillover": ["spill_fod_ref"],
            "SNO Referral Onboarding": ["onboard_ref"],
            "SOC Referral CPOD": ["soc_cpod_ref"],
            "SOC Referral Cost": ["soc_rb_cpfod"],
            "SOC Referral Transacting": ["soc_transact_ref"],
            "SOC Referral Spillover": ["soc_spill_fod_ref"],
        }
    },
    "FR Channel": {
        "passcode": "fr123",
        "sections": {
            "SNO FR": ["cost_fr_salary","cost_fr_count","cost_fr_tl_salary","cost_fr_tl_count","cost_fr_incentive"],
            "SNO FR Transacting": ["transact_fr"],
            "SNO FR Spillover": ["spill_fod_fr"],
            "SNO FR Onboarding": ["onboard_fr"],
            "SOC FR": ["soc_fr_count","soc_tl_count","soc_fr_initiatives","soc_fr_extra"],
            "SOC FR Transacting": ["soc_transact_fr"],
            "SOC FR Spillover": ["soc_spill_fod_fr"],
        }
    },
    "Influencer Channel": {
        "passcode": "inf123",
        "sections": {
            "SNO Influencer Cost": ["cost_influencer_payout","cost_inf_tl_salary","cost_inf_tl_count"],
            "SNO Influencer Transacting": ["transact_influencers"],
            "SNO Influencer Spillover": ["spill_fod_influencers"],
            "SNO Influencer Onboarding": ["onboard_influencers"],
            "SOC Influencer Transacting": ["soc_transact_influencers"],
            "SOC Influencer Spillover": ["soc_spill_fod_influencers"],
        }
    },
    "Rejoiner & Spillover": {
        "passcode": "rej123",
        "sections": {
            "SNO Rejoiner": ["sno_rejoiner"],
            "SNO Spillover Cost": ["sno_spillover_28","cost_spillover_28","cost_spillover_over_28"],
            "SNO Spillover FOD": ["spill_fod_ref","spill_fod_google","spill_fod_affiliate","spill_fod_ssu","spill_fod_fr","spill_fod_agency","spill_fod_influencers"],
            "SOC Rejoiner": ["soc_rejoiner","soc_rejoiner_cost"],
            "SOC Spillover Cost": ["soc_spillover_28","soc_spillover_over_28","soc_cost_spillover_28","soc_cost_spillover_over_28"],
            "SOC Spillover FOD": ["soc_spill_fod_ref","soc_spill_fod_google","soc_spill_fod_affiliate","soc_spill_fod_ssu","soc_spill_fod_fr","soc_spill_fod_agency","soc_spill_fod_influencers"],
        }
    },
    "Comms Channel": {
        "passcode": "comms123",
        "sections": {
            "SNO SMS": ["cost_sms_fresh","cost_sms_rejoiner"],
            "SNO WhatsApp": ["cost_whatsapp_fresh","cost_whatsapp_rejoiner"],
            "SNO OBE/RTC": ["cost_obe_rtc"],
            "SNO Autodialer": ["cost_autodialer"],
            "SNO BGV Fresh": ["cost_bgv_fresh","cost_bgv_address"],
            "SNO BGV Rejoiner": ["cost_bgv_rejoiner"],
            "SNO Misc": ["cost_apsflyer","cost_pivot_roots","cost_btl"],
            "SOC SMS": ["soc_sms_fresh","soc_sms_rejoiner"],
            "SOC WhatsApp": ["soc_whatsapp_fresh","soc_whatsapp_rejoiner"],
            "SOC BGV": ["soc_bgv"],
            "SOC TC Incentive": ["soc_tc_incentive"],
            "SOC BTL": ["soc_btl"],
        }
    },
}

USERS = {}
for cn, cd in CHANNELS.items():
    USERS[cn] = {"hash": hashlib.sha256(cd["passcode"].encode()).hexdigest()[:12], "admin": False}
USERS["Tulika"] = {"hash": hashlib.sha256("admin123".encode()).hexdigest()[:12], "admin": True}

METRIC_LABELS = {}
ALL_METRICS_SET = set()
for cd in CHANNELS.values():
    for keys in cd["sections"].values():
        for k in keys:
            ALL_METRICS_SET.add(k)
            if k not in METRIC_LABELS:
                METRIC_LABELS[k] = k.replace("_"," ").title()

ck = ["cost_flatpay","cost_leakage","cost_shouldering","cost_jb","cost_agency",
      "cost_google_supper","cost_google_im_app","cost_insurance","cost_ob_fee",
      "cost_bgv_fresh","cost_sms_fresh","cost_whatsapp_fresh",
      "cost_fr_salary","cost_fr_tl_salary","cost_btl","cost_fr_incentive",
      "cost_influencer_payout","cost_inf_tl_salary"]
fk = ["transact_ref","transact_google","transact_ssu","transact_fr",
      "transact_agency","transact_influencers"]

def chk(raw): return hashlib.sha256(raw.encode()).hexdigest()[:12]
def wkl(dt): return f"WK{dt.isocalendar()[1]}-{dt.year}"
def cur_ws(): return datetime.now() - timedelta(days=datetime.now().weekday())
def get_last_week_dates():
    today = datetime.now()
    lm = today - timedelta(days=today.weekday() + 7)
    ls = lm + timedelta(days=6)
    return lm.strftime("%Y-%m-%d"), ls.strftime("%Y-%m-%d")

# Snowflake
@lru_cache
def get_snowflake_conn():
    try:
        import snowflake.connector
        if SF_PRIVATE_KEY:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.backends import default_backend
            key_bytes = SF_PRIVATE_KEY.encode() if isinstance(SF_PRIVATE_KEY,str) else SF_PRIVATE_KEY
            pkb = serialization.load_pem_private_key(key_bytes,password=None,backend=default_backend())
            conn = snowflake.connector.connect(account=SF_ACCOUNT,user=SF_USER,private_key=pkb,warehouse=SF_WAREHOUSE,role=SF_ROLE)
        else:
            token = SF_ACCESS_TOKEN
            if not token:
                logging.warning("Snowflake access token not set")
                return None
            conn = snowflake.connector.connect(account=SF_ACCOUNT,authenticator="oauth",token=token,warehouse=SF_WAREHOUSE,role=SF_ROLE)
        cur = conn.cursor()
        cur.execute(f"USE WAREHOUSE {SF_WAREHOUSE}")
        return conn
    except Exception as e:
        logging.warning(f"Snowflake connection failed: {e}")
        return None

def fetch_orders_from_snowflake(d1,d2):
    conn = get_snowflake_conn()
    if conn is None: return None
    query = f"""
    with cte as(
    select dt,city_name,order_flag,count(distinct order_id) orders,
    case when order_flag='Instamart' then 'IM' else 'Food' end as fleet,
    case when city_name in ('Chennai','Ahmedabad','Hyderabad','Delhi','Bangalore','Mumbai','Vijayawada','Indore','Jaipur','Noida','Kochi','Kolkata','Lucknow','Thiruvananthapuram','Madurai','Pune','Central Goa','Gorakhpur','Kanpur','Pondicherry','Surat','Bhubaneswar','Vizag','Mysore','Noida 1','Dehradun','Guwahati','Tirupur','Chandigarh','Faridabad','Gurgaon','Manipal','Coimbatore','Thrissur','Patna','Vadodara','Rajkot','Agra','Varanasi','Amritsar','Mangaluru','Ludhiana','Raipur') then 'SNO' else 'SOC' end as City_Type
    from (
    select distinct order_id,case when POST_STATUS in('Completed') then 'Completed' else 'Cancelled' end POST_STATUS,
    ORDERED_TIME,m.city_id::varchar as city_id,c.name city_name,
    (case when lower(delivery_partner) in('rapido','shadowfax','loadshare','adloggs') then 'SFX_Food'
    when lower(delivery_partner) in('dominos','petpooja','urbanpiper','faasos','eatclub','popeyes') then 'Dominos_Food'
    else 'Food' end) Order_Flag,dt
    from facts.public.dp_order_fact m
    left join de.swiggy.area a on a.id=m.area_id
    left join de.swiggy.zone z on z.id=a.zone_id
    left join de.swiggy.city c on c.id=z.city_id
    where to_date(dt) between '{d1}' and '{d2}'
    and restaurant_id not in(select distinct restaurant_id from analytics.public.restaurant_attributes
    where(business_classifier='Stores Lite' or parent_id in('591159')))
    and lower(post_status)='completed' and ignore_order_flag=0
    group by all
    union all
    select distinct a.order_id,case when status in('DELIVERY_DELIVERED') then 'Completed' else 'Cancelled' end POST_STATUS,
    a.ORDERED_TIME,a.CITY_ID,a.city,'Instamart' ORDER_FLAG,a.dt
    from analytics.public.IM_PARENT_ORDER_FACT a
    where a.status='DELIVERY_DELIVERED' and a.dt between '{d1}' and '{d2}'
    group by all
    union all
    select distinct id order_id,case when status in('DELIVERY_DELIVERED') then 'Completed' else 'Cancelled' end POST_STATUS,
    ORDERED_TIME,city_id::varchar city_id,city,
    (case when lower(type) in('instamart') and lower(city) not in('budhwal') then 'Instamart'
    when lower(CATEGORY) ilike '%liquor%' then 'Alcohol' else 'stores' end) order_flag,dt
    from ANALYTICS.PUBLIC.STORES_ORDER_FACT
    where dt between '{d1}' and '{d2}' and lower(CATEGORY) ilike '%liquor%' and status in('DELIVERY_DELIVERED')
    union all
    select distinct id order_id,case when status in('DELIVERY_DELIVERED') then 'Completed' else 'Cancelled' end POST_STATUS,
    ORDERED_TIME,city_id::varchar city_id,city,
    (case when ORDER_TYPE is not null then 'Genie' end) order_flag,dt
    from ANALYTICS.PUBLIC.GENIE_ORDER_FACT
    where dt between '{d1}' and '{d2}' and status in('DELIVERY_DELIVERED')
    union all
    select distinct id order_id,case when status in('DELIVERY_DELIVERED') then 'Completed' else 'Cancelled' end POST_STATUS,
    ORDERED_TIME,city_id::varchar city_id,city,
    (case when SID is not null then 'Genie' end) order_flag,dt
    from ANALYTICS.PUBLIC.GENIE_B2B_ORDER_FACT
    where dt between '{d1}' and '{d2}' and status in('DELIVERY_DELIVERED')
    union all
    select order_id,ORDER_STATUS POST_STATUS,ordered_time,a.city_id,b.name city,'Snacc' ORDER_FLAG,to_date(dt) dt
    from ANALYTICS.PUBLIC.SNACC_ORDER_FACT a
    left join de.swiggy.city b on a.city_id=b.id
    where lower(CATEGORY) in('snacc') and lower(ORDER_STATUS) in('completed')
    and dt between '{d1}' and '{d2}'
    ) group by all order by city_name
    )
    select City_Type,sum(orders) as total_orders
    from cte where fleet='IM' group by 1 order by 1
    """
    try:
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        results = {"SNO_IM":0,"SOC_IM":0}
        for row in rows:
            ct,od = row[0],int(row[1])
            results[f"{ct}_IM"] = od
        return results
    except Exception as e:
        logging.error(f"Snowflake query failed: {e}")
        return None
    finally:
        try: cur.close()
        except: pass

# Google Sheets
@lru_cache
def get_gsheet_client():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
        creds_dict = None
        if GCP_SA_JSON: creds_dict = json.loads(GCP_SA_JSON)
        elif GCP_SA_FILE:
            with open(GCP_SA_FILE) as f: creds_dict = json.load(f)
        if creds_dict is None:
            logging.warning("No GCP credentials provided")
            return None
        scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(creds_dict),scope)
        return gspread.authorize(creds)
    except Exception as e:
        logging.warning(f"GSheet auth failed: {e}")
        return None

def get_sheet():
    client = get_gsheet_client()
    if client is None: return None
    try:
        sheet = client.open_by_key(SHEET_ID)
        try: return sheet.get_worksheet_by_id(int(SHEET_GID))
        except: return sheet.sheet1
    except Exception as e:
        logging.warning(f"get_sheet failed: {e}")
        return None

def read_all_submissions():
    ws = get_sheet()
    if ws is None: return []
    try: records = ws.get_all_records()
    except: return []
    subs = []
    for row in records:
        for mk,val in row.items():
            if mk in ("channel","week_label","submitted_at"): continue
            try: v = float(val) if val and str(val).strip()!="" else 0.0
            except: v = 0.0
            if v != 0:
                subs.append({"channel":row.get("channel",""),"week_label":row.get("week_label",""),"metric":mk,"value":v})
    return subs

def write_submission(channel,week_label,data):
    ws = get_sheet()
    if ws is None: raise HTTPException(status_code=503,detail="Google Sheets not connected")
    try:
        all_records = ws.get_all_records()
        headers = ws.row_values(1)
        all_keys = sorted(set(data.keys()))
        expected = ["channel","week_label","submitted_at"] + all_keys
        if set(expected) != set(headers) or not headers:
            ws.clear()
            ws.append_row(expected)
            headers = expected
        row_idx = None
        for i,rec in enumerate(all_records):
            if rec.get("channel")==channel and rec.get("week_label")==week_label:
                row_idx = i+2; break
        now = datetime.now().isoformat()
        row_data = {"channel":channel,"week_label":week_label,"submitted_at":now}
        row_data.update(data)
        row_list = [row_data.get(h,"") for h in headers]
        if row_idx:
            for ci,val in enumerate(row_list): ws.update_cell(row_idx,ci+1,val)
        else: ws.append_row(row_list)
        return True
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500,detail=f"Sheet error: {e}")

def write_orders_to_sheet(week_label,orders_data):
    return write_submission("Auto-Fetch (Orders)",week_label,{"orders_sno":float(orders_data.get("SNO_IM",0)),"orders_soc":float(orders_data.get("SOC_IM",0))})

def gm(wk,subs):
    result = {}
    for s in subs:
        if s["week_label"]==wk: result[s["metric"]] = result.get(s["metric"],0)+s["value"]
    return result

def generate_excel(subs):
    o = BytesIO()
    aw = sorted(set(s["week_label"] for s in subs))
    with pd.ExcelWriter(o,engine="openpyxl") as wb:
        rd = []
        for mk in sorted(ALL_METRICS_SET):
            row = {"Metric":METRIC_LABELS.get(mk,mk)}
            for w in aw: row[w] = sum(s["value"] for s in subs if s["week_label"]==w and s["metric"]==mk)
            rd.append(row)
        pd.DataFrame(rd).to_excel(wb,sheet_name="Data",index=False)
        sm = []
        for w in aw:
            d = gm(w,subs)
            sm.append({"Week":w,"Cost":sum(d.get(k,0) for k in ck),
                        "FOD":int(sum(d.get(k,0) for k in fk)),
                        "CPFOD":round(sum(d.get(k,0) for k in ck)/max(sum(d.get(k,0) for k in fk),1))})
        pd.DataFrame(sm).to_excel(wb,sheet_name="Summary",index=False)
    o.seek(0)
    return o

# Token store
TOKEN_STORE: dict[str,dict] = {}
LAST_FETCHED_ORDERS: dict[str,tuple] = {}

def generate_token(): return secrets.token_urlsafe(32)

# Auth
def get_current_user_cookie(request: Request) -> Optional[dict]:
    token = request.cookies.get("sno_token","")
    if not token: return None
    entry = TOKEN_STORE.get(token)
    if not entry: return None
    if datetime.now() > entry["expires_at"]: del TOKEN_STORE[token]; return None
    return entry["user"]

def get_current_user_api(request: Request) -> dict:
    auth = request.headers.get("Authorization","")
    if not auth.startswith("Bearer "): raise HTTPException(status_code=401,detail="Missing token")
    token = auth[7:]
    entry = TOKEN_STORE.get(token)
    if not entry or datetime.now()>entry["expires_at"]: raise HTTPException(status_code=401,detail="Invalid token")
    return entry["user"]

def require_admin_api(user: dict = Depends(get_current_user_api)) -> dict:
    if not user.get("is_admin"): raise HTTPException(status_code=403,detail="Admin required")
    return user

# FastAPI app
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__),"templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__),"static")

app = FastAPI(title="SNO Hiring Cost Tracker")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
if os.path.isdir(STATIC_DIR): app.mount("/static",StaticFiles(directory=STATIC_DIR),name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ── API: Auth ──
@app.post("/api/auth/login")
def api_login(body: LoginRequest):
    u = USERS.get(body.name)
    if not u or u["hash"]!=chk(body.passcode): raise HTTPException(status_code=401,detail="Invalid credentials")
    token = generate_token()
    user_info = {"name":body.name,"is_admin":u["admin"],"channel":None if u["admin"] else body.name}
    TOKEN_STORE[token] = {"user":user_info,"expires_at":datetime.now()+timedelta(seconds=TOKEN_TTL)}
    return {"token":token,"user":user_info}

@app.post("/api/auth/logout")
def api_logout(user: dict = Depends(get_current_user_api)):
    keys = [k for k,v in TOKEN_STORE.items() if v.get("user",{}).get("name")==user.get("name")]
    for k in keys: del TOKEN_STORE[k]
    return {"ok":True}

@app.get("/api/auth/me")
def api_me(user: dict = Depends(get_current_user_api)): return user

@app.get("/api/auth/channels")
def api_channels(): return [{"name":cn,"passcode":cd["passcode"]} for cn,cd in CHANNELS.items()]

# ── API: Submissions ──
@app.get("/api/submissions/form")
def api_submission_form(user: dict = Depends(get_current_user_api)):
    wsd = cur_ws(); d1,d2 = get_last_week_dates()
    orders = fetch_orders_from_snowflake(d1,d2)
    defaults = {}
    if orders:
        defaults["orders_sno"]=float(orders.get("SNO_IM",0))
        defaults["orders_soc"]=float(orders.get("SOC_IM",0))
    return {"label":wkl(wsd),"start_date":wsd.strftime("%Y-%m-%d"),"defaults":defaults}

@app.get("/api/submissions/my")
def api_my_submissions(user: dict = Depends(get_current_user_api)):
    channel = user.get("channel") or user["name"]
    return [s for s in read_all_submissions() if s["channel"]==channel]

@app.post("/api/submissions")
def api_submit(body: SubmissionRequest, user: dict = Depends(get_current_user_api)):
    channel = user.get("channel") or user["name"]
    try: write_submission(channel,body.week_label,body.metrics); return {"ok":True}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500,detail=str(e))

@app.get("/api/submissions/orders")
def api_orders(user: dict = Depends(get_current_user_api)):
    d1,d2 = get_last_week_dates()
    orders = fetch_orders_from_snowflake(d1,d2)
    if orders is None: raise HTTPException(status_code=503,detail="Snowflake unavailable")
    return orders

# ── API: Admin ──
@app.post("/api/admin/orders/fetch")
def api_admin_fetch_orders(user: dict = Depends(require_admin_api)):
    d1,d2 = get_last_week_dates()
    orders = fetch_orders_from_snowflake(d1,d2)
    if orders is None: raise HTTPException(status_code=503,detail="Snowflake unavailable")
    return orders

@app.post("/api/admin/orders/save")
def api_admin_save_orders(user: dict = Depends(require_admin_api)):
    d1,d2 = get_last_week_dates(); dw = datetime.strptime(d1,"%Y-%m-%d")
    orders = fetch_orders_from_snowflake(d1,d2)
    if orders is None: raise HTTPException(status_code=503,detail="No orders to save")
    try: write_orders_to_sheet(wkl(dw),orders); return {"ok":True}
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500,detail=str(e))

@app.get("/api/admin/submissions/list")
def api_admin_submissions(user: dict = Depends(require_admin_api)):
    subs = read_all_submissions()
    weeks = sorted(set(s["week_label"] for s in subs),reverse=True)
    return {"weeks":weeks}

@app.get("/api/admin/submissions")
def api_admin_submissions_by_week(week: str, user: dict = Depends(require_admin_api)):
    subs = read_all_submissions()
    result = {}
    for s in subs:
        if s["week_label"]==week:
            ch = s["channel"]
            if ch not in result: result[ch] = {}
            result[ch][s["metric"]] = s["value"]
    return {"week":week,"channels":result}

@app.get("/api/admin/wow")
def api_admin_wow(user: dict = Depends(require_admin_api)):
    subs = read_all_submissions()
    wa = sorted(set(s["week_label"] for s in subs),reverse=True)
    if len(wa)<2: return {"weeks":wa,"wow":[]}
    tw,pw = wa[0],wa[1]; d1,d2 = gm(tw,subs),gm(pw,subs)
    rows = []
    for ch_name in sorted(CHANNELS.keys()):
        c1 = sum(d1.get(k,0) for k in ck); c2 = sum(d2.get(k,0) for k in ck)
        rows.append({"channel":ch_name,"metric":"Total Cost","current_value":c1,"prev_value":c2,
                      "change":c1-c2,"change_pct":f"{(c1-c2)/max(c2,1)*100:+.1f}%" if c2 else "N/A",
                      "tag_class":"tag-down" if c1<c2 else "tag-up"})
    return {"weeks":wa,"current_week":tw,"prev_week":pw,"wow":rows}

@app.get("/api/admin/cpfod")
def api_admin_cpfod(base_week: str, compare_week: str, user: dict = Depends(require_admin_api)):
    subs = read_all_submissions(); da,db = gm(base_week,subs),gm(compare_week,subs)
    analysis = []
    for ch,key in zip(["Referral","Google","Agency","FR","SSU Direct"],
                       ["transact_ref","transact_google","transact_agency","transact_fr","transact_ssu"]):
        va,vb = int(da.get(key,0)),int(db.get(key,0)); delta = vb-va
        analysis.append({"channel":ch,"metric":"FOD","base_val":va,"compare_val":vb,"change_val":delta,"change_str":f"{delta:+,}"})
    return {"base_week":base_week,"compare_week":compare_week,"analysis":analysis}

@app.get("/api/admin/channels")
def api_admin_channels_detail(user: dict = Depends(require_admin_api)):
    return {"channels":{cn:{"passcode":cd["passcode"],"sections":cd["sections"]} for cn,cd in CHANNELS.items()}}

@app.get("/api/admin/export")
def api_admin_export(user: dict = Depends(require_admin_api)):
    subs = read_all_submissions(); o = generate_excel(subs)
    filename = f"sno_data_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(o,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition":f"attachment; filename={filename}"})

@app.get("/api/health")
def api_health():
    sf_ok = get_snowflake_conn() is not None
    gs_ok = get_sheet() is not None
    return {"status":"ok","snowflake_connected":sf_ok,"gsheets_connected":gs_ok}

# ── HTML Pages ──
@app.get("/",include_in_schema=False)
def index(request: Request):
    user = get_current_user_cookie(request)
    if user is None: return RedirectResponse("/login",status_code=303)
    if user.get("is_admin"): return RedirectResponse("/admin",status_code=303)
    return RedirectResponse("/submission",status_code=303)

@app.get("/login",include_in_schema=False)
def login_page(request: Request):
    channels_list = [{"name":cn,"passcode":cd["passcode"]} for cn,cd in CHANNELS.items()]
    return templates.TemplateResponse(request,"login.html",{"user":None,"channels":channels_list})

@app.post("/login",include_in_schema=False)
def login_submit(request: Request, name: str = Form(...), passcode: str = Form(...)):
    u = USERS.get(name)
    channels_list = [{"name":cn,"passcode":cd["passcode"]} for cn,cd in CHANNELS.items()]
    if not u or u["hash"]!=chk(passcode):
        return templates.TemplateResponse(request,"login.html",
            {"user":None,"channels":channels_list,"msg":"Invalid credentials","msg_type":"error"})
    token = generate_token()
    user_info = {"name":name,"is_admin":u["admin"],"channel":None if u["admin"] else name}
    TOKEN_STORE[token] = {"user":user_info,"expires_at":datetime.now()+timedelta(seconds=TOKEN_TTL)}
    resp = RedirectResponse("/",status_code=303)
    resp.set_cookie("sno_token",token,httponly=True,max_age=TOKEN_TTL)
    return resp

@app.get("/logout",include_in_schema=False)
def logout_page(request: Request):
    token = request.cookies.get("sno_token","")
    if token in TOKEN_STORE: del TOKEN_STORE[token]
    resp = RedirectResponse("/login",status_code=303)
    resp.delete_cookie("sno_token")
    return resp

@app.get("/submission",include_in_schema=False)
def submission_page(request: Request):
    user = get_current_user_cookie(request)
    if user is None: return RedirectResponse("/login",status_code=303)
    channel_name = user.get("channel") or user["name"]
    cd = CHANNELS.get(channel_name)
    if cd is None:
        cf = [{"name":cn,"passcode":cx["passcode"]} for cn,cx in CHANNELS.items()]
        return templates.TemplateResponse(request,"login.html",
            {"user":None,"channels":cf,"msg":f"Channel '{channel_name}' not found.","msg_type":"error"})
    wsd = cur_ws(); wlbl = wkl(wsd); wsd_str = wsd.strftime("%d %b %Y")
    defaults = {}
    d1,d2 = get_last_week_dates(); orders = fetch_orders_from_snowflake(d1,d2)
    if orders:
        defaults["orders_sno"]=float(orders.get("SNO_IM",0))
        defaults["orders_soc"]=float(orders.get("SOC_IM",0))
    sections = []
    for sec,keys in cd["sections"].items():
        metrics = []
        for mk in keys:
            metrics.append({"key":mk,"label":METRIC_LABELS.get(mk,mk.replace("_"," ").title()),
                           "default_value":defaults.get(mk,None),"is_order":mk in("orders_sno","orders_soc")})
        sections.append({"section_name":sec,"metrics":metrics})
    subs = read_all_submissions()
    past_weeks = sorted(set(s["week_label"] for s in subs if s["channel"]==channel_name),reverse=True)
    return templates.TemplateResponse(request,"submission.html",
        {"user":user,"channel_name":channel_name,"week_label":wlbl,"week_start":wsd_str,
         "sections":sections,"past_weeks":past_weeks[:10]})

@app.post("/submission",include_in_schema=False)
def submission_submit(request: Request, week_label: str = Form(...)):
    user = get_current_user_cookie(request)
    if user is None: return RedirectResponse("/login",status_code=303)
    channel = user.get("channel") or user["name"]
    cd = CHANNELS.get(channel,{})
    clean = {}
    form_data = dict(request.form)
    for sec,keys in cd.get("sections",{}).items():
        for mk in keys:
            raw = form_data.get(mk,"").strip().replace(",","")
            try: clean[mk] = float(raw) if raw else 0.0
            except ValueError: clean[mk] = 0.0
    try: write_submission(channel,week_label,clean); msg,msg_type = "Submitted successfully!","success"
    except HTTPException as e: msg,msg_type = str(e.detail),"error"
    wsd = cur_ws(); wlbl = wkl(wsd); wsd_str = wsd.strftime("%d %b %Y")
    sections = []
    for sec,keys in cd.get("sections",{}).items():
        metrics = []
        for mk in keys:
            metrics.append({"key":mk,"label":METRIC_LABELS.get(mk,mk.replace("_"," ").title()),
                           "default_value":clean.get(mk,None),"is_order":mk in("orders_sno","orders_soc")})
        sections.append({"section_name":sec,"metrics":metrics})
    subs = read_all_submissions()
    past_weeks = sorted(set(s["week_label"] for s in subs if s["channel"]==channel),reverse=True)
    return templates.TemplateResponse(request,"submission.html",
        {"user":user,"channel_name":channel,"week_label":wlbl,"week_start":wsd_str,
         "sections":sections,"past_weeks":past_weeks[:10],"msg":msg,"msg_type":msg_type})

@app.get("/admin",include_in_schema=False)
def admin_page(request: Request, week: Optional[str]=None, tab: Optional[str]=None,
                base_week: Optional[str]=None, compare_week: Optional[str]=None):
    user = get_current_user_cookie(request)
    if user is None: return RedirectResponse("/login",status_code=303)
    if not user.get("is_admin"): return RedirectResponse("/submission",status_code=303)
    subs = read_all_submissions()
    weeks = sorted(set(s["week_label"] for s in subs),reverse=True)
    selected_week = week or (weeks[0] if weeks else "")
    channels_data = []
    if selected_week:
        week_subs = [s for s in subs if s["week_label"]==selected_week]
        for ch_name in sorted(set(s["channel"] for s in week_subs)):
            metrics = {}; total_cost = 0; total_hiring = 0
            for s_ in week_subs:
                if s_["channel"]==ch_name:
                    metrics[METRIC_LABELS.get(s_["metric"],s_["metric"])] = s_["value"]
                    if s_["metric"] in ck: total_cost += s_["value"]
                    if s_["metric"] in fk: total_hiring += int(s_["value"])
            channels_data.append({"channel":ch_name,"week_label":selected_week,"metrics":metrics,
                                  "total_cost":total_cost,"total_hiring":total_hiring})
    wow = []
    if len(weeks)>=2:
        tw,pw = weeks[0],weeks[1]; d1_,d2_ = gm(tw,subs),gm(pw,subs)
        for ch_name in sorted(CHANNELS.keys()):
            c1 = sum(d1_.get(k,0) for k in ck); c2 = sum(d2_.get(k,0) for k in ck)
            wow.append({"channel":ch_name,"metric":"Total Cost","current_value":c1,"prev_value":c2,
                        "change_pct":f"{(c1-c2)/max(c2,1)*100:+.1f}%" if c2 else "N/A",
                        "tag_class":"tag-down" if c1<c2 else "tag-up"})
    cpfod = []
    if base_week and compare_week:
        da,db = gm(base_week,subs),gm(compare_week,subs)
        for ch,key in zip(["Referral","Google","Agency","FR","SSU Direct"],
                           ["transact_ref","transact_google","transact_agency","transact_fr","transact_ssu"]):
            va,vb = int(da.get(key,0)),int(db.get(key,0)); delta = vb-va
            cpfod.append({"channel":ch,"metric":"FOD","base_val":va,"compare_val":vb,"change_val":delta,"change_str":f"{delta:+,}"})
    admin_channels_list = [
        {"name":cn,"passcode":cd["passcode"],"sections_count":len(cd["sections"]),
         "metrics_count":sum(len(k) for k in cd["sections"].values())}
        for cn,cd in CHANNELS.items()
    ]
    fetched_orders = None
    token = request.cookies.get("sno_token","")
    entry = LAST_FETCHED_ORDERS.get(token)
    if entry:
        orders_dict,wlbl = entry
        fetched_orders = {"sno_im":orders_dict["SNO_IM"],"soc_im":orders_dict["SOC_IM"],"week_label":wlbl}
    return templates.TemplateResponse(request,"admin_dashboard.html",{
        "user":user,"weeks_available":weeks,"selected_week":selected_week,
        "channels_data":channels_data,"wow":wow,"cpfod":cpfod,
        "base_week":base_week or (weeks[0] if len(weeks)>=1 else ""),
        "compare_week":compare_week or (weeks[1] if len(weeks)>=2 else ""),
        "admin_channels":admin_channels_list,"fetched_orders":fetched_orders,"token":token})

@app.post("/admin/orders/fetch",include_in_schema=False)
def admin_fetch_orders_html(request: Request):
    user = get_current_user_cookie(request)
    if user is None or not user.get("is_admin"): return RedirectResponse("/login",status_code=303)
    d1,d2 = get_last_week_dates(); orders = fetch_orders_from_snowflake(d1,d2)
    if orders:
        result = {"SNO_IM":orders.get("SNO_IM",0),"SOC_IM":orders.get("SOC_IM",0)}
        dw = datetime.strptime(d1,"%Y-%m-%d")
        LAST_FETCHED_ORDERS[request.cookies.get("sno_token","")] = (result,wkl(dw))
    return RedirectResponse("/admin",status_code=303)

@app.post("/admin/orders/save",include_in_schema=False)
def admin_save_orders_html(request: Request):
    user = get_current_user_cookie(request)
    if user is None or not user.get("is_admin"): return RedirectResponse("/login",status_code=303)
    entry = LAST_FETCHED_ORDERS.get(request.cookies.get("sno_token",""))
    if entry:
        orders,wlbl = entry; write_orders_to_sheet(wlbl,orders)
    return RedirectResponse("/admin",status_code=303)

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT","8000")))