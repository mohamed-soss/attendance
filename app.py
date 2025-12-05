import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import plotly.express as px
from streamlit_option_menu import option_menu
import gspread
from google.oauth2.service_account import Credentials

# ——————————————————————————————————————————————————
# CONFIG & GOOGLE SHEETS
# ——————————————————————————————————————————————————
EGYPT_TZ = ZoneInfo("Africa/Cairo")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def get_credentials():
    if "gcp_service_account" in st.secrets:
        return Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    else:
        try:
            return Credentials.from_service_account_file("attendance-477813-1ab662e24347.json", scopes=SCOPES)
        except:
            st.error("Google Sheets credentials missing!")
            return None

CREDS = get_credentials()
if CREDS:
    CLIENT = gspread.authorize(CREDS)
    SHEET = CLIENT.open("AttendanceSheet").sheet1
else:
    SHEET = None

EXPECTED_COLUMNS = ['User','Date','CheckIn','CheckOut','Break1Start','Break1End','Break2Start','Break2End',
                    'Break3Start','Break3End','TotalHours','BreakDuration','Active']

TIME_COLUMNS = ['CheckIn','CheckOut','Break1Start','Break1End','Break2Start','Break2End','Break3Start','Break3End']

# ——————————————————————————————————————————————————
# LOAD DATA + AUTO CREATE DEFAULT USER
# ——————————————————————————————————————————————————
@st.cache_data(ttl=60)
def load_data():
    if not SHEET:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)
    
    records = SHEET.get_all_records()
    df = pd.DataFrame(records)
    
    # Add missing columns
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA if col != 'Active' else True
    
    # Clean & type
    df.replace("", pd.NA, inplace=True)
    for c in TIME_COLUMNS:
        df[c] = df[c].astype("string")
    df['TotalHours'] = pd.to_numeric(df['TotalHours'], errors='coerce').fillna(0.0)
    df['BreakDuration'] = pd.to_numeric(df['BreakDuration'], errors='coerce').fillna(0.0)
    df['Active'] = df['Active'].apply(lambda x: str(x).strip().lower() not in ['false','0','no','f'])
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    
    # FORCE DEFAULT USER IF NONE EXIST
    if df.empty or df[df['Active']].empty:
        default_row = {
            'User': 'Default User', 'Date': datetime.now(EGYPT_TZ).date(),
            'CheckIn': pd.NA, 'CheckOut': pd.NA,
            'Break1Start': pd.NA, 'Break1End': pd.NA,
            'Break2Start': pd.NA, 'Break2End': pd.NA,
            'Break3Start': pd.NA, 'Break3End': pd.NA,
            'TotalHours': 0.0, 'BreakDuration': 0.0, 'Active': True
        }
        df = pd.concat([df, pd.DataFrame([default_row])], ignore_index=True)
        save_data(df)  # Immediate save so user appears instantly
        st.success("Default user created – refresh once!")
    
    return df

def save_data(df_to_save=None):
    if not SHEET: return
    df_save = (df_to_save or df).copy()
    df_save['Date'] = df_save['Date'].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')
    try:
        SHEET.clear()
        SHEET.append_row(EXPECTED_COLUMNS)
        SHEET.append_rows(df_save.fillna('').values.tolist())
    except Exception as e:
        st.error(f"Save failed: {e}")

# Load data
df = load_data()

# ——————————————————————————————————————————————————
# CYBERPUNK DESIGN (exactly as you love it)
# ——————————————————————————————————————————————————
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;500;600;700&family=Exo+2:wght@100;200;300;400;500;600;700;800;900&display=swap');
:root {
    --primary: #00f2ff; --secondary: #ff00ff; --accent: #00ff88;
    --bg: #0a0a1f; --card: rgba(10,15,35,0.8);
}
body, .stApp {background: linear-gradient(135deg,#0a0a1f,#1a1a3e,#0f1f3f); color:white; font-family:'Rajdhani',sans-serif;}
.cyber-header {font-family:'Orbitron',monospace; font-size:3.5rem; text-align:center;
    background: linear-gradient(45deg,var(--primary),var(--secondary),var(--accent));
    -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
    text-shadow:0 0 30px rgba(0,242,255,0.6);}
.cyber-card {background:var(--card); backdrop-filter:blur(20px); border:1px solid rgba(0,242,255,0.4);
    border-radius:15px; padding:2rem; margin:1.5rem 0; box-shadow:0 8px 32px rgba(0,0,0,0.4);}
.stButton>button {background:linear-gradient(135deg,rgba(0,242,255,0.1),rgba(255,0,255,0.1));
    border:1px solid var(--primary)!important; color:white!important; padding:1rem 2rem!important;
    font-family:'Exo 2',sans-serif!important; text-transform:uppercase; border-radius:10px!important;}
.stButton>button:hover {box-shadow:0 0 25px rgba(0,242,255,0.7)!important; transform:translateY(-3px)!important;}
</style>
""", unsafe_allow_html=True)

# ——————————————————————————————————————————————————
# SIDEBAR NAVIGATION
# ——————————————————————————————————————————————————
with st.sidebar:
    st.markdown("<h2 style='color:var(--primary); text-align:center;'>QUANTUM</h2>", unsafe_allow_html=True)
    selected = option_menu("", ["USER PORTAL", "COMMAND CENTER"],
                           icons=["rocket", "gear"], default_index=0)

# ——————————————————————————————————————————————————
# USER PORTAL – FIXED FORM (NO MORE WARNINGS!)
# ——————————————————————————————————————————————————
if selected == "USER PORTAL":
    st.markdown("<h1 class='cyber-header'>QUANTUM ATTENDANCE</h1>", unsafe_allow_html=True)
    
    active_users = sorted(df[df['Active'] == True]['User'].dropna().unique())
    
    # THE ONLY FORM – ALWAYS HAS A SUBMIT BUTTON
    with st.form("user_selection_form"):
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        
        if not len(active_users):
            st.warning("No active users – creating default user...")
            st.form_submit_button("Please wait...", disabled=True)
        else:
            col1, col2 = st.columns([3,1])
            with col1:
                chosen_user = st.selectbox("SELECT YOUR IDENTITY", active_users)
            with col2:
                submit_btn = st.form_submit_button("ACTIVATE")
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        if submit_btn and len(active_users):
            st.session_state.selected_user = chosen_user
            st.success(f"Welcome, {chosen_user}!")
            st.rerun()

    # ——— USER IS LOGGED IN ———
    if st.session_state.get("selected_user"):
        user = st.session_state.selected_user
        today = datetime.now(EGYPT_TZ).date()
        row = df[(df['User'] == user) & (df['Date'].dt.date == today)]
        
        if row.empty:
            if st.button("INITIATE NEW SESSION", use_container_width=True):
                new = pd.DataFrame([{
                    'User': user, 'Date': today, 'Active': True,
                    'CheckIn': pd.NA, 'CheckOut': pd.NA,
                    'Break1Start': pd.NA, 'Break1End': pd.NA,
                    'Break2Start': pd.NA, 'Break2End': pd.NA,
                    'Break3Start': pd.NA, 'Break3End': pd.NA,
                    'TotalHours': 0.0, 'BreakDuration': 0.0
                }])
                global df
                df = pd.concat([df, new], ignore_index=True)
                save_data(df)
                st.success("Session started!")
                st.rerun()
        else:
            idx = row.index[0]
            st.markdown("<div class='cyber-card'><h3 style='text-align:center; color:#00ff88;'>LIVE CONTROLS</h3>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("CHECK IN", use_container_width=True) and pd.isna(df.at[idx, 'CheckIn']):
                    df.at[idx, 'CheckIn'] = datetime.now(EGYPT_TZ).strftime("%I:%M %p")
                    save_data(df)
                    st.rerun()
            with c2:
                for i in range(1,4):
                    if st.button(f"BREAK {i} START", use_container_width=True):
                        df.at[idx, f'Break{i}Start'] = datetime.now(EGYPT_TZ).strftime("%I:%M %p")
                        save_data(df)
                        st.rerun()
                    if st.button(f"BREAK {i} END", use_container_width=True):
                        df.at[idx, f'Break{i}End'] = datetime.now(EGYPT_TZ).strftime("%I:%M %p")
                        save_data(df)
                        st.rerun()
            with c3:
                if st.button("CHECK OUT", use_container_width=True) and pd.isna(df.at[idx, 'CheckOut']):
                    df.at[idx, 'CheckOut'] = datetime.now(EGYPT_TZ).strftime("%I:%M %p")
                    save_data(df)
                    st.success("Checked out!")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

# ——————————————————————————————————————————————————
# COMMAND CENTER (Admin)
# ——————————————————————————————————————————————————
elif selected == "COMMAND CENTER":
    st.markdown("<h1 class='cyber-header'>COMMAND CENTER</h1>", unsafe_allow_html=True)
    pwd = st.text_input("Enter Access Code", type="password")
    if pwd == "admin123":
        st.success("Access Granted")
        edited = st.data_editor(df, use_container_width=True, num_rows="dynamic")
        if st.button("SAVE ALL CHANGES"):
            save_data(edited)
            st.success("All data saved!")
            st.rerun()
    elif pwd:
        st.error("Wrong code")

# Real-time clock
st.sidebar.markdown(f"""
<div class='cyber-card' style='text-align:center;padding:1rem;'>
    <small style='color:#00f2ff'>EGYPT TIME</small><br>
    <b style='font-family:Orbitron; color:#00ff88; font-size:1.3rem;'>
        {datetime.now(EGYPT_TZ).strftime('%H:%M:%S')}
    </b>
</div>
""", unsafe_allow_html=True)
