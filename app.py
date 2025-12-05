import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import plotly.express as px
from streamlit_option_menu import option_menu
import streamlit.components.v1 as components
import gspread
from google.oauth2.service_account import Credentials
import time
import random

# Egypt timezone
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# Google Sheets setup
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
def get_credentials():
    if 'gcp_service_account' in st.secrets:
        creds_dict = dict(st.secrets['gcp_service_account'])
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        try:
            return Credentials.from_service_account_file("attendance-477813-1ab662e24347.json", scopes=SCOPES)
        except:
            st.error("Google Sheets credentials not found. Please check your secrets configuration.")
            return None

# Initialize Google Sheets client
try:
    CREDS = get_credentials()
    if CREDS:
        CLIENT = gspread.authorize(CREDS)
        SHEET = CLIENT.open("AttendanceSheet").sheet1
    else:
        SHEET = None
        st.error("Failed to initialize Google Sheets connection")
except Exception as e:
    st.error(f"Error initializing Google Sheets: {str(e)}")
    SHEET = None

# Define expected columns
EXPECTED_COLUMNS = ['User', 'Date', 'CheckIn', 'CheckOut',
                    'Break1Start', 'Break1End', 'Break2Start', 'Break2End',
                    'Break3Start', 'Break3End', 'TotalHours', 'BreakDuration', 'Active']

# Time-related columns to enforce string dtype
TIME_COLUMNS = ['CheckIn', 'CheckOut', 'Break1Start', 'Break1End',
                'Break2Start', 'Break2End', 'Break3Start', 'Break3End']

# Function to convert to boolean safely
def to_boolean(value):
    if pd.isna(value) or value == '':
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in ['true', '1', 't', 'y', 'yes']:
            return True
        elif lowered in ['false', '0', 'f', 'n', 'no']:
            return False
        else:
            return True
    return True

# Load data from Google Sheets
try:
    data = SHEET.get_all_records()
    df = pd.DataFrame(data)
    
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            if col == 'Active':
                df[col] = True
            elif col in TIME_COLUMNS:
                df[col] = pd.NA
            else:
                df[col] = pd.NA
                
    df.replace('', pd.NA, inplace=True)
    
    for col in TIME_COLUMNS:
        df[col] = df[col].astype("string").fillna(pd.NA)
        
    df['TotalHours'] = pd.to_numeric(df['TotalHours'], errors='coerce').fillna(0.0).astype("float64")
    df['BreakDuration'] = pd.to_numeric(df['BreakDuration'], errors='coerce').fillna(0.0).astype("float64")
    df['Active'] = df['Active'].apply(to_boolean).astype("boolean")
    
    if not df.empty and 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    
except Exception as e:
    st.error(f"Error loading data from Google Sheets: {str(e)}")
    dtypes = {col: "string" for col in TIME_COLUMNS}
    dtypes.update({'User': 'string', 'Date': 'string', 'TotalHours': 'float64',
                   'BreakDuration': 'float64', 'Active': 'boolean'})
    df = pd.DataFrame(columns=EXPECTED_COLUMNS).astype(dtypes)

# Function to save data to Google Sheets
def save_data():
    global df
    try:
        df_save = df.copy()
        df_save['Date'] = df_save['Date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
        )
        SHEET.clear()
        SHEET.append_row(EXPECTED_COLUMNS)
        data = df_save.fillna('').values.tolist()
        if data:
            SHEET.append_rows(data)
    except Exception as e:
        st.error(f"Error saving data to Google Sheets: {str(e)}")

# Function to restore data from Excel
def restore_from_excel(uploaded_file):
    global df
    try:
        uploaded_df = pd.read_excel(uploaded_file, sheet_name='DataMatrix')
        if not all(col in uploaded_df.columns for col in ['User', 'Date']):
            st.error("Uploaded Excel file must contain 'User' and 'Date' columns.")
            return False
            
        for col in EXPECTED_COLUMNS:
            if col not in uploaded_df.columns:
                if col == 'Active':
                    uploaded_df[col] = True
                elif col in TIME_COLUMNS:
                    uploaded_df[col] = pd.NA
                else:
                    uploaded_df[col] = pd.NA
                    
        for col in TIME_COLUMNS:
            uploaded_df[col] = uploaded_df[col].astype("string").fillna(pd.NA)
            
        uploaded_df['User'] = uploaded_df['User'].astype("string")
        uploaded_df['Date'] = pd.to_datetime(uploaded_df['Date'], errors='coerce')
        uploaded_df['TotalHours'] = uploaded_df['TotalHours'].astype("float64")
        uploaded_df['BreakDuration'] = uploaded_df['BreakDuration'].astype("float64")
        uploaded_df['Active'] = uploaded_df['Active'].apply(to_boolean).astype("boolean")
        
        df = pd.concat([df, uploaded_df]).drop_duplicates(subset=['User', 'Date', 'CheckIn'], keep='last').reset_index(drop=True)
        save_data()
        return True
        
    except Exception as e:
        st.error(f"Error restoring data: {str(e)}")
        return False

# Function to calculate shift date
def get_shift_date():
    now = datetime.now(EGYPT_TZ)
    if now.hour < 4 or (now.hour == 4 and now.minute == 0):
        return (now - timedelta(days=1)).date()
    else:
        return now.date()

# Function to format time as 12-hour string
def format_time(dt):
    if isinstance(dt, datetime):
        return dt.strftime("%I:%M %p").lstrip("0")
    return dt

# Function to parse time string with shift date for calculations
def parse_time(time_str, shift_date):
    if pd.isna(time_str) or not isinstance(time_str, str):
        return None
    try:
        dt = datetime.strptime(f"{shift_date} {time_str}", "%Y-%m-%d %I:%M %p")
        dt = dt.replace(tzinfo=EGYPT_TZ)
        if dt.hour < 16 and time_str.endswith("AM"):
            dt += timedelta(days=1)
        return dt
    except ValueError:
        return None

# Function to calculate total hours and break duration
def calculate_times(row, shift_date):
    check_in = parse_time(row['CheckIn'], shift_date) if pd.notna(row['CheckIn']) else None
    check_out = parse_time(row['CheckOut'], shift_date) if pd.notna(row['CheckOut']) else None
    if check_in and check_out:
        total_hours = (check_out - check_in).total_seconds() / 3600
    else:
        total_hours = 0
    break_duration = 0
    for i in range(1, 4):
        start_col = f'Break{i}Start'
        end_col = f'Break{i}End'
        break_start = parse_time(row[start_col], shift_date) if pd.notna(row[start_col]) else None
        break_end = parse_time(row[end_col], shift_date) if pd.notna(row[end_col]) else None
        if break_start and break_end:
            break_duration += (break_end - break_start).total_seconds() / 3600
    return total_hours, break_duration

# ULTRA MODERN CSS WITH ADVANCED ANIMATIONS
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;500;600;700&family=Exo+2:wght@100;200;300;400;500;600;700;800;900&display=swap');
    
    :root {
        --primary-glow: #00f2ff;
        --secondary-glow: #ff00ff;
        --accent-glow: #00ff88;
        --warning-glow: #ffaa00;
        --deep-space: #0a0a1f;
        --nebula-purple: #1a1a3e;
        --cosmic-blue: #0f1f3f;
        --stardust: rgba(255,255,255,0.1);
        --text-neon: #ffffff;
        --cyber-border: rgba(0, 242, 255, 0.3);
    }
    
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    body, .stApp {
        background: linear-gradient(135deg, var(--deep-space) 0%, var(--nebula-purple) 50%, var(--cosmic-blue) 100%);
        background-size: 400% 400%;
        animation: cosmicShift 20s ease infinite;
        color: var(--text-neon);
        font-family: 'Rajdhani', sans-serif;
        overflow-x: hidden;
        min-height: 100vh;
    }
    
    @keyframes cosmicShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    
    /* Animated Starfield Background */
    body::before {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: 
            radial-gradient(2px 2px at 20px 30px, #eee, transparent),
            radial-gradient(2px 2px at 40px 70px, #fff, transparent),
            radial-gradient(1px 1px at 90px 40px, #fff, transparent),
            radial-gradient(1px 1px at 130px 80px, #fff, transparent),
            radial-gradient(2px 2px at 160px 30px, #eee, transparent);
        background-size: 200px 200px;
        animation: starsMove 100s linear infinite;
        z-index: -1;
        opacity: 0.3;
    }
    
    @keyframes starsMove {
        from { transform: translateY(0px); }
        to { transform: translateY(-200px); }
    }
    
    /* Cyber Grid Overlay */
    body::after {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: 
            linear-gradient(90deg, transparent 95%, rgba(0, 242, 255, 0.03) 95%),
            linear-gradient(0deg, transparent 95%, rgba(0, 242, 255, 0.03) 95%);
        background-size: 50px 50px;
        z-index: -1;
        pointer-events: none;
    }
    
    /* Main Container Enhancements */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }
    
    /* Cyber Header */
    .cyber-header {
        font-family: 'Orbitron', monospace;
        font-weight: 900;
        font-size: 3.5rem;
        text-align: center;
        margin-bottom: 2rem;
        background: linear-gradient(45deg, var(--primary-glow), var(--secondary-glow), var(--accent-glow));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        text-shadow: 
            0 0 30px rgba(0, 242, 255, 0.5),
            0 0 60px rgba(255, 0, 255, 0.3),
            0 0 90px rgba(0, 255, 136, 0.2);
        animation: textGlow 3s ease-in-out infinite alternate;
        position: relative;
    }
    
    @keyframes textGlow {
        from {
            text-shadow: 
                0 0 20px rgba(0, 242, 255, 0.5),
                0 0 40px rgba(255, 0, 255, 0.3),
                0 0 60px rgba(0, 255, 136, 0.2);
        }
        to {
            text-shadow: 
                0 0 30px rgba(0, 242, 255, 0.8),
                0 0 60px rgba(255, 0, 255, 0.5),
                0 0 90px rgba(0, 255, 136, 0.4);
        }
    }
    
    /* Cyber Card */
    .cyber-card {
        background: rgba(10, 15, 35, 0.7);
        backdrop-filter: blur(20px);
        border: 1px solid var(--cyber-border);
        border-radius: 15px;
        padding: 2rem;
        margin: 1.5rem 0;
        position: relative;
        overflow: hidden;
        box-shadow: 
            0 8px 32px rgba(0, 0, 0, 0.3),
            inset 0 1px 0 rgba(255, 255, 255, 0.1);
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        animation: cardAppear 0.6s ease-out;
    }
    
    @keyframes cardAppear {
        from {
            opacity: 0;
            transform: translateY(30px) scale(0.95);
        }
        to {
            opacity: 1;
            transform: translateY(0) scale(1);
        }
    }
    
    .cyber-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(0, 242, 255, 0.1), transparent);
        transition: left 0.6s ease;
    }
    
    .cyber-card:hover::before {
        left: 100%;
    }
    
    .cyber-card:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 
            0 15px 40px rgba(0, 242, 255, 0.3),
            0 0 30px rgba(255, 0, 255, 0.2),
            inset 0 1px 0 rgba(255, 255, 255, 0.2);
        border-color: rgba(0, 242, 255, 0.6);
    }
    
    /* Cyber Button */
    .stButton > button {
        background: linear-gradient(135deg, rgba(0, 242, 255, 0.1), rgba(255, 0, 255, 0.1)) !important;
        border: 1px solid var(--cyber-border) !important;
        color: var(--text-neon) !important;
        padding: 1rem 2rem !important;
        font-family: 'Exo 2', sans-serif !important;
        font-weight: 600 !important;
        font-size: 1.1rem !important;
        border-radius: 10px !important;
        transition: all 0.3s ease !important;
        position: relative !important;
        overflow: hidden !important;
        text-transform: uppercase !important;
        letter-spacing: 1px !important;
        backdrop-filter: blur(10px) !important;
    }
    
    .stButton > button::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(0, 242, 255, 0.4), transparent);
        transition: left 0.5s ease;
    }
    
    .stButton > button:hover::before {
        left: 100%;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, rgba(0, 242, 255, 0.2), rgba(255, 0, 255, 0.2)) !important;
        box-shadow: 
            0 0 20px rgba(0, 242, 255, 0.4),
            0 0 40px rgba(255, 0, 255, 0.2) !important;
        transform: translateY(-2px) !important;
        border-color: var(--primary-glow) !important;
    }
    
    /* Status Indicators */
    .status-active {
        color: var(--accent-glow);
        text-shadow: 0 0 10px currentColor;
        animation: pulse 2s infinite;
    }
    
    .status-pending {
        color: var(--warning-glow);
        text-shadow: 0 0 10px currentColor;
        animation: blink 1.5s infinite;
    }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
    }
    
    @keyframes blink {
        0%, 50% { opacity: 1; }
        51%, 100% { opacity: 0.3; }
    }
    
    /* Navigation Enhancement */
    .css-1lcbmhc {
        background: rgba(10, 15, 35, 0.9) !important;
        backdrop-filter: blur(20px);
        border-right: 1px solid var(--cyber-border) !important;
    }
    
    /* Input Fields */
    .stTextInput > div > div > input, 
    .stSelectbox > div > select {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid var(--cyber-border) !important;
        color: var(--text-neon) !important;
        border-radius: 8px !important;
        padding: 12px !important;
        font-family: 'Rajdhani', sans-serif !important;
        transition: all 0.3s ease !important;
    }
    
    .stTextInput > div > div > input:focus, 
    .stSelectbox > div > select:focus {
        border-color: var(--primary-glow) !important;
        box-shadow: 0 0 15px rgba(0, 242, 255, 0.3) !important;
        background: rgba(255, 255, 255, 0.1) !important;
    }
    
    /* Dataframe Styling */
    .dataframe {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid var(--cyber-border) !important;
        border-radius: 10px !important;
        overflow: hidden !important;
    }
    
    /* Progress Bars */
    .stProgress > div > div > div {
        background: linear-gradient(90deg, var(--primary-glow), var(--accent-glow)) !important;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, var(--primary-glow), var(--secondary-glow));
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, var(--accent-glow), var(--primary-glow));
    }
    
    /* Floating Elements */
    .floating {
        animation: floating 3s ease-in-out infinite;
    }
    
    @keyframes floating {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None
if 'last_action' not in st.session_state:
    st.session_state.last_action = None

# Sidebar with enhanced navigation
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; margin-bottom: 2rem;'>
            <div class='floating' style='font-size: 2rem;'>⚡</div>
            <h3 style='color: var(--primary-glow); font-family: Orbitron;'>QUANTUM CONTROL</h3>
        </div>
    """, unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title="",
        options=["🚀 USER PORTAL", "⚙️ COMMAND CENTER"],
        icons=["", ""],
        menu_icon="",
        default_index=0,
        styles={
            "container": {
                "padding": "0!important", 
                "background-color": "rgba(10, 15, 35, 0.8)",
                "backdrop-filter": "blur(10px)",
                "border": "1px solid var(--cyber-border)",
                "border-radius": "10px"
            },
            "icon": {"color": "var(--primary-glow)", "font-size": "20px"},
            "nav-link": {
                "font-size": "16px",
                "text-align": "left",
                "margin": "5px",
                "padding": "15px",
                "--hover-color": "rgba(0, 242, 255, 0.1)",
                "border-radius": "8px",
                "font-family": "Exo 2, sans-serif",
                "font-weight": "600"
            },
            "nav-link-selected": {
                "background": "linear-gradient(135deg, rgba(0, 242, 255, 0.2), rgba(255, 0, 255, 0.2))",
                "border": "1px solid var(--primary-glow)",
                "color": "white",
                "box-shadow": "0 0 15px rgba(0, 242, 255, 0.3)"
            },
        }
    )

# User Portal
if selected == "🚀 USER PORTAL":
    st.markdown("<h1 class='cyber-header'>QUANTUM ATTENDANCE SYSTEM</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        active_users = sorted(df[df['Active'] == True]['User'].unique().tolist())
        
        with st.form(key="user_selection_form"):
            if not active_users:
                st.markdown("<p class='status-pending'>No active users available. Please contact the admin to add users.</p>", unsafe_allow_html=True)
                user_name = None
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    user_name = st.selectbox("SELECT YOUR IDENTITY", options=active_users, placeholder="Choose User...", key="user_select")
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    submitted = st.form_submit_button("🚀 ACTIVATE", use_container_width=True)
                
                if submitted:
                    if user_name:
                        st.session_state.selected_user = user_name
                        st.session_state.last_action = f"User {user_name} activated"
                    else:
                        st.error("Please select a user before submitting.")
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.selected_user:
        user_name = st.session_state.selected_user
        user_records = df[df['User'] == user_name]
        user_active = user_records['Active'].any() if not user_records.empty else True
        
        if not user_active:
            st.error("⚠️ ACCESS DENIED: User account has been deactivated.")
            st.session_state.selected_user = None
        else:
            shift_date = get_shift_date()
            user_rows = df[(df['User'] == user_name) & (df['Date'] == str(shift_date))]
            
            # Start New Session
            col1, col2, col3 = st.columns([2, 1, 2])
            with col2:
                if st.button("🎯 INITIATE NEW SESSION", use_container_width=True, key="start_session"):
                    new_row = {
                        'User': user_name, 'Date': str(shift_date), 'Active': True,
                        'CheckIn': pd.NA, 'CheckOut': pd.NA, 'TotalHours': 0.0, 'BreakDuration': 0.0
                    }
                    for i in range(1, 4):
                        new_row[f'Break{i}Start'] = pd.NA
                        new_row[f'Break{i}End'] = pd.NA
                    
                    new_row_df = pd.DataFrame([new_row]).astype({
                        'User': 'string', 'Date': 'string', 'CheckIn': 'string', 'CheckOut': 'string',
                        'Break1Start': 'string', 'Break1End': 'string', 'Break2Start': 'string', 
                        'Break2End': 'string', 'Break3Start': 'string', 'Break3End': 'string',
                        'TotalHours': 'float64', 'BreakDuration': 'float64', 'Active': 'boolean'
                    })
                    df = pd.concat([df, new_row_df], ignore_index=True)
                    save_data()
                    st.session_state.last_action = "New session initialized"
                    st.success("🚀 SESSION INITIALIZED")
                    st.rerun()

            if not user_rows.empty:
                row_index = user_rows.index[-1]
                
                # Action Buttons Grid
                st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
                st.markdown("<h3 style='color: var(--primary-glow); text-align: center;'>MISSION CONTROL</h3>", unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.button("🟢 CHECK IN", use_container_width=True, key=f"check_in_{row_index}") and pd.isna(df.at[row_index, 'CheckIn']):
                        df.at[row_index, 'CheckIn'] = format_time(datetime.now(EGYPT_TZ))
                        total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                        df.at[row_index, 'TotalHours'] = total_hours
                        df.at[row_index, 'BreakDuration'] = break_duration
                        save_data()
                        st.session_state.last_action = "Checked in"
                        st.rerun()
                
                with col2:
                    for i in range(1, 4):
                        if st.button(f"☕ BREAK {i} START", use_container_width=True, key=f"break_{i}_start_{row_index}") and pd.isna(df.at[row_index, f'Break{i}Start']) and pd.notna(df.at[row_index, 'CheckIn']):
                            if i == 1 or (pd.notna(df.at[row_index, f'Break{i-1}End'])):
                                df.at[row_index, f'Break{i}Start'] = format_time(datetime.now(EGYPT_TZ))
                                total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                                df.at[row_index, 'TotalHours'] = total_hours
                                df.at[row_index, 'BreakDuration'] = break_duration
                                save_data()
                                st.session_state.last_action = f"Break {i} started"
                                st.rerun()
                
                with col3:
                    for i in range(1, 4):
                        if st.button(f"🔙 BREAK {i} END", use_container_width=True, key=f"break_{i}_end_{row_index}") and pd.notna(df.at[row_index, f'Break{i}Start']) and pd.isna(df.at[row_index, f'Break{i}End']):
                            df.at[row_index, f'Break{i}End'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = f"Break {i} ended"
                            st.rerun()
                    
                    if st.button("🔴 CHECK OUT", use_container_width=True, key=f"check_out_{row_index}") and pd.notna(df.at[row_index, 'CheckIn']) and pd.isna(df.at[row_index, 'CheckOut']):
                        if all(pd.notna(df.at[row_index, f'Break{i}End']) for i in range(1, 4) if pd.notna(df.at[row_index, f'Break{i}Start'])):
                            df.at[row_index, 'CheckOut'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = "Checked out"
                            st.rerun()
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                # Current Session Status
                st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
                st.markdown("<h3 style='color: var(--accent-glow);'>LIVE SESSION STATUS</h3>", unsafe_allow_html=True)
                
                status_data = {
                    "Check In": df.at[row_index, 'CheckIn'],
                    "Check Out": df.at[row_index, 'CheckOut'],
                    "Total Hours": f"{df.at[row_index, 'TotalHours']:.2f} hours",
                    "Break Duration": f"{df.at[row_index, 'BreakDuration']:.2f} hours"
                }
                
                for i in range(1, 4):
                    status_data[f"Break {i} Start"] = df.at[row_index, f'Break{i}Start']
                    status_data[f"Break {i} End"] = df.at[row_index, f'Break{i}End']
                
                cols = st.columns(3)
                col_idx = 0
                for key, value in status_data.items():
                    with cols[col_idx]:
                        st.metric(
                            label=key,
                            value=value if pd.notna(value) else "⏳ PENDING",
                            delta="ACTIVE" if "Start" in key and pd.notna(value) and pd.isna(status_data.get(key.replace("Start", "End"), None)) else None
                        )
                    col_idx = (col_idx + 1) % 3
                
                st.markdown("</div>", unsafe_allow_html=True)

# Admin Dashboard - COMPLETE AND WORKING VERSION
elif selected == "⚙️ COMMAND CENTER":
    st.markdown("<h1 class='cyber-header'>QUANTUM COMMAND CENTER</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        admin_password = st.text_input("🔐 ENTER ACCESS CODE", type="password", placeholder="Quantum Access Key...")
        st.markdown("</div>", unsafe_allow_html=True)
    
    if admin_password == "admin123":
        
        # Data Restoration Section
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📊 DATA RESTORATION MODULE</h3>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Upload Excel file to restore data", type=["xlsx"])
        if uploaded_file:
            if restore_from_excel(uploaded_file):
                st.success("🚀 DATA MATRIX RESTORED SUCCESSFULLY!")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Matrix Editor
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>🛠️ DATA MATRIX EDITOR</h3>", unsafe_allow_html=True)
        
        # Filter options
        col1, col2 = st.columns(2)
        with col1:
            filter_user = st.selectbox("FILTER BY USER", options=['All'] + sorted(df['User'].unique().tolist()), key='filter_user')
        with col2:
            filter_date = st.selectbox("FILTER BY DATE", options=['All'] + sorted(df['Date'].dt.strftime('%Y-%m-%d').unique().tolist()), key='filter_date')
        
        filtered_df = df
        if filter_user != 'All':
            filtered_df = filtered_df[filtered_df['User'] == filter_user]
        if filter_date != 'All':
            filtered_df = filtered_df[filtered_df['Date'].dt.strftime('%Y-%m-%d') == filter_date]
        
        # Ensure time columns are strings before editing
        for col in TIME_COLUMNS:
            filtered_df[col] = filtered_df[col].astype("string").fillna(pd.NA)
        
        # Calculate totals before editing
        for idx, row in filtered_df.iterrows():
            total_hours, break_duration = calculate_times(row, row['Date'].date())
            filtered_df.at[idx, 'TotalHours'] = total_hours
            filtered_df.at[idx, 'BreakDuration'] = break_duration
        
        # Editable DataFrame
        edited_df = st.data_editor(
            filtered_df,
            column_config={
                "User": st.column_config.TextColumn("User"),
                "Date": st.column_config.DateColumn("Date"),
                "CheckIn": st.column_config.TextColumn("Check In", help="Format: HH:MM AM/PM (e.g., 04:00 PM)"),
                "CheckOut": st.column_config.TextColumn("Check Out", help="Format: HH:MM AM/PM"),
                "Break1Start": st.column_config.TextColumn("Break 1 Start", help="Format: HH:MM AM/PM"),
                "Break1End": st.column_config.TextColumn("Break 1 End", help="Format: HH:MM AM/PM"),
                "Break2Start": st.column_config.TextColumn("Break 2 Start", help="Format: HH:MM AM/PM"),
                "Break2End": st.column_config.TextColumn("Break 2 End", help="Format: HH:MM AM/PM"),
                "Break3Start": st.column_config.TextColumn("Break 3 Start", help="Format: HH:MM AM/PM"),
                "Break3End": st.column_config.TextColumn("Break 3 End", help="Format: HH:MM AM/PM"),
                "TotalHours": st.column_config.NumberColumn("Total Hours", disabled=True),
                "BreakDuration": st.column_config.NumberColumn("Break Duration", disabled=True),
                "Active": st.column_config.CheckboxColumn("Active")
            },
            use_container_width=True,
            height=400
        )
        
        if st.button("💾 SAVE DATA MATRIX", use_container_width=True):
            for idx, row in edited_df.iterrows():
                total_hours, break_duration = calculate_times(row, row['Date'].date())
                edited_df.at[idx, 'TotalHours'] = total_hours
                edited_df.at[idx, 'BreakDuration'] = break_duration
            # Ensure time columns remain strings
            for col in TIME_COLUMNS:
                edited_df[col] = edited_df[col].astype("string").fillna(pd.NA)
            # Ensure Active is boolean
            edited_df['Active'] = edited_df['Active'].apply(to_boolean).astype("boolean")
            df.update(edited_df)
            df.loc[edited_df.index] = edited_df
            save_data()
            st.success("✅ DATA MATRIX UPDATED SUCCESSFULLY!")
            st.session_state.last_action = "Data matrix updated"
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Analytics Section
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📈 QUANTUM ANALYTICS</h3>", unsafe_allow_html=True)
        
        # Total Hours per User Bar Chart
        total_hours_df = df.groupby('User')['TotalHours'].sum().reset_index()
        if not total_hours_df.empty:
            fig_bar = px.bar(total_hours_df, x='User', y='TotalHours', title='TOTAL HOURS PER USER',
                             color='TotalHours', color_continuous_scale='viridis')
            fig_bar.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', 
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#ffffff',
                title_font_size=20,
                title_x=0.5
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            # User Trend
            analytics_user = st.selectbox("SELECT USER FOR TREND ANALYSIS", options=sorted(df['User'].unique().tolist()), key='analytics_user')
            if analytics_user:
                user_data = df[df['User'] == analytics_user].sort_values('Date')
                if not user_data.empty:
                    fig_line = px.line(user_data, x='Date', y='TotalHours', title=f'HOURS TREND: {analytics_user}',
                                       markers=True, color_discrete_sequence=['#00ff88'])
                    fig_line.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)', 
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff'
                    )
                    st.plotly_chart(fig_line, use_container_width=True)
        
        with col2:
            # Break Duration Pie Chart
            avg_break = df.groupby('User')['BreakDuration'].mean().reset_index()
            if not avg_break.empty:
                fig_pie = px.pie(avg_break, values='BreakDuration', names='User', title='AVERAGE BREAK DURATION')
                fig_pie.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)', 
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#ffffff'
                )
                st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # User Management
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>👥 USER MANAGEMENT</h3>", unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["➕ ADD USER", "✏️ EDIT SESSION", "🗑️ REMOVE USER"])
        
        with tab1:
            st.markdown("<h4 style='color: var(--accent-glow);'>ADD NEW USER</h4>", unsafe_allow_html=True)
            new_user = st.text_input("Enter new user name", placeholder="New User Identity...")
            if st.button("🔧 ADD USER", use_container_width=True) and new_user:
                user_records = df[df['User'] == new_user]
                if user_records.empty or not user_records['Active'].any():
                    new_row = {
                        'User': new_user,
                        'Date': str(get_shift_date()),
                        'Active': True,
                        'CheckIn': pd.NA,
                        'CheckOut': pd.NA,
                        'Break1Start': pd.NA,
                        'Break1End': pd.NA,
                        'Break2Start': pd.NA,
                        'Break2End': pd.NA,
                        'Break3Start': pd.NA,
                        'Break3End': pd.NA,
                        'TotalHours': 0.0,
                        'BreakDuration': 0.0
                    }
                    new_row_df = pd.DataFrame([new_row]).astype({
                        'User': 'string', 'Date': 'string', 'CheckIn': 'string', 'CheckOut': 'string',
                        'Break1Start': 'string', 'Break1End': 'string', 'Break2Start': 'string', 
                        'Break2End': 'string', 'Break3Start': 'string', 'Break3End': 'string',
                        'TotalHours': 'float64', 'BreakDuration': 'float64', 'Active': 'boolean'
                    })
                    df = pd.concat([df, new_row_df], ignore_index=True)
                    save_data()
                    st.success(f"✅ USER {new_user} AUTHORIZED")
                    st.session_state.last_action = f"User {new_user} added"
                    st.rerun()
                else:
                    st.warning(f"⚠️ USER {new_user} ALREADY EXISTS AND IS ACTIVE")
        
        with tab2:
            st.markdown("<h4 style='color: var(--accent-glow);'>EDIT USER SESSION</h4>", unsafe_allow_html=True)
            edit_user = st.selectbox("SELECT USER", options=['None'] + sorted(df['User'].unique().tolist()), key='edit_user')
            if edit_user != 'None':
                user_sessions = df[df['User'] == edit_user]
                if not user_sessions.empty:
                    session_dates = sorted(user_sessions['Date'].dt.strftime('%Y-%m-%d').unique().tolist())
                    edit_date = st.selectbox("SELECT SESSION DATE", options=session_dates, key='edit_date')
                    session_row = user_sessions[user_sessions['Date'].dt.strftime('%Y-%m-%d') == edit_date].iloc[-1]
                    session_index = session_row.name
                    
                    with st.form(key=f"edit_session_form_{session_index}"):
                        st.write(f"Editing session for **{edit_user}** on **{edit_date}**")
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            check_in = st.text_input("Check In", value=session_row['CheckIn'] if pd.notna(session_row['CheckIn']) else "", placeholder="04:00 PM")
                            break1_start = st.text_input("Break 1 Start", value=session_row['Break1Start'] if pd.notna(session_row['Break1Start']) else "", placeholder="06:00 PM")
                            break1_end = st.text_input("Break 1 End", value=session_row['Break1End'] if pd.notna(session_row['Break1End']) else "", placeholder="06:30 PM")
                            break2_start = st.text_input("Break 2 Start", value=session_row['Break2Start'] if pd.notna(session_row['Break2Start']) else "", placeholder="08:00 PM")
                        
                        with col2:
                            break2_end = st.text_input("Break 2 End", value=session_row['Break2End'] if pd.notna(session_row['Break2End']) else "", placeholder="08:30 PM")
                            break3_start = st.text_input("Break 3 Start", value=session_row['Break3Start'] if pd.notna(session_row['Break3Start']) else "", placeholder="10:00 PM")
                            break3_end = st.text_input("Break 3 End", value=session_row['Break3End'] if pd.notna(session_row['Break3End']) else "", placeholder="10:30 PM")
                            check_out = st.text_input("Check Out", value=session_row['CheckOut'] if pd.notna(session_row['CheckOut']) else "", placeholder="12:00 AM")
                        
                        active = st.checkbox("Active", value=session_row['Active'])
                        
                        if st.form_submit_button("💾 SAVE SESSION", use_container_width=True):
                            # Validate time format
                            time_fields = [check_in, check_out, break1_start, break1_end, break2_start, break2_end, break3_start, break3_end]
                            valid = True
                            for field in time_fields:
                                if field:
                                    try:
                                        datetime.strptime(f"{edit_date} {field}", "%Y-%m-%d %I:%M %p")
                                    except ValueError:
                                        st.error(f"❌ INVALID TIME FORMAT: {field}. Use HH:MM AM/PM (e.g., 04:00 PM).")
                                        valid = False
                            if valid:
                                df.at[session_index, 'CheckIn'] = check_in if check_in else pd.NA
                                df.at[session_index, 'CheckOut'] = check_out if check_out else pd.NA
                                df.at[session_index, 'Break1Start'] = break1_start if break1_start else pd.NA
                                df.at[session_index, 'Break1End'] = break1_end if break1_end else pd.NA
                                df.at[session_index, 'Break2Start'] = break2_start if break2_start else pd.NA
                                df.at[session_index, 'Break2End'] = break2_end if break2_end else pd.NA
                                df.at[session_index, 'Break3Start'] = break3_start if break3_start else pd.NA
                                df.at[session_index, 'Break3End'] = break3_end if break3_end else pd.NA
                                df.at[session_index, 'Active'] = active
                                total_hours, break_duration = calculate_times(df.loc[session_index], edit_date)
                                df.at[session_index, 'TotalHours'] = total_hours
                                df.at[session_index, 'BreakDuration'] = break_duration
                                # Ensure time columns remain strings
                                for col in TIME_COLUMNS:
                                    df[col] = df[col].astype("string").fillna(pd.NA)
                                save_data()
                                st.success(f"✅ SESSION FOR {edit_user} ON {edit_date} UPDATED!")
                                st.session_state.last_action = f"Session for {edit_user} updated"
                                st.rerun()
        
        with tab3:
            st.markdown("<h4 style='color: var(--accent-glow);'>REMOVE USER</h4>", unsafe_allow_html=True)
            remove_user = st.selectbox("SELECT USER TO REMOVE", options=['None'] + sorted(df['User'].unique().tolist()), key='remove_user')
            action = st.selectbox("ACTION", options=["Keep User", "Delete User (Keep Data)", "Delete User and Data"], key='user_action')
            
            if st.button("⚡ EXECUTE ACTION", use_container_width=True) and remove_user != 'None':
                user_records = df[df['User'] == remove_user]
                if user_records.empty:
                    st.error(f"❌ USER {remove_user} NOT FOUND")
                else:
                    if action == "Delete User (Keep Data)":
                        df.loc[df['User'] == remove_user, 'Active'] = False
                        save_data()
                        st.success(f"✅ USER {remove_user} DELETED. HISTORICAL DATA RETAINED.")
                    elif action == "Delete User and Data":
                        df = df[df['User'] != remove_user]
                        save_data()
                        st.success(f"✅ USER {remove_user} AND ALL ASSOCIATED DATA DELETED.")
                    st.session_state.last_action = f"User {remove_user} {action.lower()}"
                    st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Export
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📤 DATA EXPORT</h3>", unsafe_allow_html=True)
        
        def get_excel_download_link(df):
            df_download = df.copy()
            df_download['Date'] = df_download['Date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
            )
            with pd.ExcelWriter('attendance.xlsx', engine='xlsxwriter') as writer:
                df_download.to_excel(writer, index=False, sheet_name='DataMatrix')
            with open('attendance.xlsx', 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode()
            return f'<a href="data:application/octet-stream;base64,{b64}" download="attendance.xlsx" style="display: inline-block; padding: 0.5rem 1rem; background: linear-gradient(135deg, rgba(0, 242, 255, 0.2), rgba(255, 0, 255, 0.2)); border: 1px solid var(--cyber-border); border-radius: 5px; color: var(--text-neon); text-decoration: none; font-family: Exo 2, sans-serif; font-weight: 600;">📥 DOWNLOAD DATA MATRIX</a>'
        
        st.markdown(get_excel_download_link(df), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    else:
        if admin_password:
            st.error("🚫 QUANTUM ACCESS DENIED: Invalid security credentials")

# Add floating action notification
if st.session_state.last_action:
    st.toast(f"⚡ {st.session_state.last_action}", icon="✅")
    st.session_state.last_action = None

# Add real-time clock
current_time = datetime.now(EGYPT_TZ).strftime("%Y-%m-%d %H:%M:%S")
st.sidebar.markdown(f"""
    <div class='cyber-card' style='text-align: center;'>
        <div style='font-size: 0.9rem; color: var(--primary-glow);'>QUANTUM TIME</div>
        <div style='font-family: Orbitron; font-size: 1.1rem; color: var(--accent-glow);'>{current_time}</div>
    </div>
""", unsafe_allow_html=True)
