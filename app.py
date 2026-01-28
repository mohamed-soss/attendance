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
import numpy as np

# Egypt timezone
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# Google Sheets setup - FIXED to prevent data deletion
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

# Load data from Google Sheets - FIXED to handle empty sheets
def load_data():
    try:
        # Get all records
        data = SHEET.get_all_records()
        
        if not data:  # If sheet is empty
            df = pd.DataFrame(columns=EXPECTED_COLUMNS)
        else:
            df = pd.DataFrame(data)
        
        # Ensure all expected columns exist
        for col in EXPECTED_COLUMNS:
            if col not in df.columns:
                if col == 'Active':
                    df[col] = True
                elif col in TIME_COLUMNS:
                    df[col] = pd.NA
                else:
                    df[col] = pd.NA
        
        df.replace('', pd.NA, inplace=True)
        
        # Convert data types
        for col in TIME_COLUMNS:
            df[col] = df[col].astype("string").fillna(pd.NA)
        
        df['TotalHours'] = pd.to_numeric(df['TotalHours'], errors='coerce').fillna(0.0).astype("float64")
        df['BreakDuration'] = pd.to_numeric(df['BreakDuration'], errors='coerce').fillna(0.0).astype("float64")
        df['Active'] = df['Active'].apply(to_boolean).astype("boolean")
        
        if not df.empty and 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
        return df
        
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {str(e)}")
        dtypes = {col: "string" for col in TIME_COLUMNS}
        dtypes.update({'User': 'string', 'Date': 'string', 'TotalHours': 'float64',
                       'BreakDuration': 'float64', 'Active': 'boolean'})
        return pd.DataFrame(columns=EXPECTED_COLUMNS).astype(dtypes)

# Load initial data
df = load_data()

# Function to save data to Google Sheets - FIXED to avoid data deletion
def save_data():
    try:
        df_save = df.copy()
        df_save['Date'] = df_save['Date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
        )
        
        # Convert all data to list format for Google Sheets
        values = [EXPECTED_COLUMNS] + df_save.fillna('').values.tolist()
        
        # Update the entire sheet at once (more efficient)
        SHEET.update('A1', values)
        
        return True
        
    except Exception as e:
        st.error(f"Error saving data to Google Sheets: {str(e)}")
        return False

# Function to restore data from Excel
def restore_from_excel(uploaded_file):
    try:
        uploaded_df = pd.read_excel(uploaded_file)
        
        # Check for required columns
        required_cols = ['User', 'Date']
        missing_cols = [col for col in required_cols if col not in uploaded_df.columns]
        if missing_cols:
            st.error(f"Uploaded Excel file missing required columns: {missing_cols}")
            return False
        
        # Ensure all expected columns exist
        for col in EXPECTED_COLUMNS:
            if col not in uploaded_df.columns:
                if col == 'Active':
                    uploaded_df[col] = True
                elif col in TIME_COLUMNS:
                    uploaded_df[col] = pd.NA
                else:
                    uploaded_df[col] = pd.NA
        
        # Clean and format data
        for col in TIME_COLUMNS:
            uploaded_df[col] = uploaded_df[col].astype("string").fillna(pd.NA)
        
        uploaded_df['User'] = uploaded_df['User'].astype("string")
        uploaded_df['Date'] = pd.to_datetime(uploaded_df['Date'], errors='coerce')
        
        # Handle numeric columns
        if 'TotalHours' in uploaded_df.columns:
            uploaded_df['TotalHours'] = pd.to_numeric(uploaded_df['TotalHours'], errors='coerce').fillna(0.0)
        
        if 'BreakDuration' in uploaded_df.columns:
            uploaded_df['BreakDuration'] = pd.to_numeric(uploaded_df['BreakDuration'], errors='coerce').fillna(0.0)
        
        # Handle Active column
        if 'Active' in uploaded_df.columns:
            uploaded_df['Active'] = uploaded_df['Active'].apply(to_boolean)
        
        # Append to existing data
        global df
        df = pd.concat([df, uploaded_df], ignore_index=True)
        
        # Remove duplicates (keep last entry for same user+date+checkin)
        df = df.drop_duplicates(subset=['User', 'Date', 'CheckIn'], keep='last').reset_index(drop=True)
        
        # Save to Google Sheets
        if save_data():
            st.success("Data restored successfully!")
            return True
        else:
            return False
        
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

# PROFESSIONAL MODERN CSS WITH ELEGANT ANIMATIONS
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500&family=Poppins:wght@300;400;500;600;700&display=swap');
    
    :root {
        --primary: #2563eb;
        --primary-dark: #1d4ed8;
        --primary-light: #3b82f6;
        --secondary: #7c3aed;
        --accent: #10b981;
        --warning: #f59e0b;
        --danger: #ef4444;
        --dark: #0f172a;
        --darker: #020617;
        --light: #f8fafc;
        --gray: #64748b;
        --gray-light: #e2e8f0;
        --success: #10b981;
        --glass: rgba(255, 255, 255, 0.05);
        --glass-border: rgba(255, 255, 255, 0.1);
        --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
        --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
    }
    
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    body, .stApp {
        background: linear-gradient(135deg, var(--darker) 0%, var(--dark) 50%, #1e293b 100%);
        background-attachment: fixed;
        color: var(--light);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        overflow-x: hidden;
        min-height: 100vh;
    }
    
    /* Animated background gradient */
    body::before {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: 
            radial-gradient(circle at 20% 50%, rgba(37, 99, 235, 0.15) 0%, transparent 50%),
            radial-gradient(circle at 80% 20%, rgba(124, 58, 237, 0.15) 0%, transparent 50%),
            radial-gradient(circle at 40% 80%, rgba(16, 185, 129, 0.1) 0%, transparent 50%);
        z-index: -1;
        animation: gradientShift 20s ease infinite alternate;
    }
    
    @keyframes gradientShift {
        0% {
            transform: translate(0%, 0%) scale(1);
        }
        100% {
            transform: translate(-5%, 5%) scale(1.1);
        }
    }
    
    /* Subtle grid overlay */
    body::after {
        content: '';
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-image: 
            linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
        background-size: 50px 50px;
        z-index: -1;
        pointer-events: none;
        opacity: 0.5;
    }
    
    /* Main container adjustments */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 4rem;
        max-width: 1400px;
    }
    
    /* Professional Header */
    .professional-header {
        font-family: 'Poppins', sans-serif;
        font-weight: 700;
        font-size: 2.8rem;
        text-align: center;
        margin-bottom: 2.5rem;
        background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 50%, var(--accent) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        background-size: 200% 200%;
        animation: gradientFlow 8s ease infinite;
        position: relative;
        letter-spacing: -0.5px;
    }
    
    .professional-header::after {
        content: '';
        position: absolute;
        bottom: -10px;
        left: 50%;
        transform: translateX(-50%);
        width: 100px;
        height: 4px;
        background: linear-gradient(90deg, var(--primary), var(--accent));
        border-radius: 2px;
        animation: linePulse 2s ease-in-out infinite;
    }
    
    @keyframes gradientFlow {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }
    
    @keyframes linePulse {
        0%, 100% { width: 100px; opacity: 1; }
        50% { width: 150px; opacity: 0.8; }
    }
    
    /* Glass Card */
    .glass-card {
        background: var(--glass);
        backdrop-filter: blur(16px);
        border: 1px solid var(--glass-border);
        border-radius: 16px;
        padding: 2rem;
        margin: 1.5rem 0;
        position: relative;
        overflow: hidden;
        box-shadow: var(--shadow-lg);
        transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        animation: cardFloatUp 0.6s ease-out;
    }
    
    @keyframes cardFloatUp {
        from {
            opacity: 0;
            transform: translateY(20px) scale(0.98);
        }
        to {
            opacity: 1;
            transform: translateY(0) scale(1);
        }
    }
    
    .glass-card:hover {
        transform: translateY(-4px);
        box-shadow: var(--shadow-xl);
        border-color: rgba(255, 255, 255, 0.2);
    }
    
    .glass-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 0.05),
            rgba(255, 255, 255, 0.1),
            rgba(255, 255, 255, 0.05),
            transparent
        );
        transition: left 0.7s ease;
    }
    
    .glass-card:hover::before {
        left: 100%;
    }
    
    /* Professional Button */
    .stButton > button {
        background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
        border: none !important;
        color: white !important;
        padding: 0.875rem 1.75rem !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        border-radius: 12px !important;
        transition: all 0.3s ease !important;
        position: relative !important;
        overflow: hidden !important;
        letter-spacing: 0.3px !important;
        box-shadow: var(--shadow) !important;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, var(--primary-dark) 0%, var(--primary) 100%) !important;
        transform: translateY(-2px) !important;
        box-shadow: var(--shadow-lg) !important;
    }
    
    .stButton > button:active {
        transform: translateY(0) !important;
    }
    
    .stButton > button::after {
        content: '';
        position: absolute;
        top: 50%;
        left: 50%;
        width: 0;
        height: 0;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 50%;
        transform: translate(-50%, -50%);
        transition: width 0.4s, height 0.4s;
    }
    
    .stButton > button:active::after {
        width: 200px;
        height: 200px;
    }
    
    /* Secondary Button */
    .secondary-button > button {
        background: transparent !important;
        border: 2px solid var(--primary) !important;
        color: var(--primary) !important;
    }
    
    .secondary-button > button:hover {
        background: rgba(37, 99, 235, 0.1) !important;
        border-color: var(--primary-light) !important;
        color: var(--primary-light) !important;
    }
    
    /* Status Indicators */
    .status-active {
        color: var(--accent);
        font-weight: 600;
        position: relative;
        padding-left: 1.2rem;
    }
    
    .status-active::before {
        content: '';
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 8px;
        height: 8px;
        background-color: var(--accent);
        border-radius: 50%;
        animation: pulseDot 2s infinite;
    }
    
    .status-inactive {
        color: var(--gray);
        font-weight: 500;
        position: relative;
        padding-left: 1.2rem;
    }
    
    .status-inactive::before {
        content: '';
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        width: 8px;
        height: 8px;
        background-color: var(--gray);
        border-radius: 50%;
    }
    
    @keyframes pulseDot {
        0%, 100% { 
            opacity: 1; 
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        }
        50% { 
            opacity: 0.7; 
            box-shadow: 0 0 0 10px rgba(16, 185, 129, 0);
        }
    }
    
    /* Navigation Enhancement */
    .css-1lcbmhc {
        background: rgba(15, 23, 42, 0.9) !important;
        backdrop-filter: blur(20px);
        border-right: 1px solid rgba(255, 255, 255, 0.05) !important;
    }
    
    /* Input Fields */
    .stTextInput > div > div > input,
    .stSelectbox > div > select,
    .stDateInput > div > div > input {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: var(--light) !important;
        border-radius: 10px !important;
        padding: 0.875rem 1rem !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.95rem !important;
        transition: all 0.3s ease !important;
    }
    
    .stTextInput > div > div > input:focus,
    .stSelectbox > div > select:focus,
    .stDateInput > div > div > input:focus {
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1) !important;
        background: rgba(255, 255, 255, 0.08) !important;
    }
    
    /* Dataframe Styling */
    .dataframe {
        background: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        overflow: hidden !important;
    }
    
    .dataframe th {
        background: rgba(37, 99, 235, 0.2) !important;
        color: var(--light) !important;
        font-weight: 600 !important;
        border: none !important;
        padding: 1rem !important;
    }
    
    .dataframe td {
        border-color: rgba(255, 255, 255, 0.05) !important;
        padding: 0.875rem 1rem !important;
    }
    
    /* Progress Bars */
    .stProgress > div > div > div {
        background: linear-gradient(90deg, var(--primary), var(--accent)) !important;
        border-radius: 4px !important;
    }
    
    /* Metrics */
    .stMetric {
        background: rgba(255, 255, 255, 0.03);
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .stMetric label {
        color: var(--gray) !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
    }
    
    .stMetric value {
        color: var(--light) !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
    }
    
    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, var(--primary), var(--secondary));
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, var(--primary-light), var(--secondary));
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: rgba(255, 255, 255, 0.03);
        padding: 4px;
        border-radius: 12px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-radius: 10px;
        padding: 0.75rem 1.5rem;
        font-weight: 500;
        color: var(--gray);
        transition: all 0.3s ease;
    }
    
    .stTabs [aria-selected="true"] {
        background: rgba(37, 99, 235, 0.2);
        color: var(--primary-light);
        font-weight: 600;
    }
    
    /* Toast notifications */
    .stToast {
        background: rgba(15, 23, 42, 0.95) !important;
        backdrop-filter: blur(20px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
    }
    
    /* Floating animation for elements */
    @keyframes float {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
    }
    
    .floating {
        animation: float 6s ease-in-out infinite;
    }
    
    /* Loading animation */
    @keyframes shimmer {
        0% { background-position: -1000px 0; }
        100% { background-position: 1000px 0; }
    }
    
    .shimmer {
        background: linear-gradient(90deg, 
            rgba(255,255,255,0) 0%, 
            rgba(255,255,255,0.05) 50%, 
            rgba(255,255,255,0) 100%);
        background-size: 1000px 100%;
        animation: shimmer 2s infinite linear;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None
if 'last_action' not in st.session_state:
    st.session_state.last_action = None
if 'refresh' not in st.session_state:
    st.session_state.refresh = False

# Professional Sidebar Navigation
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; margin-bottom: 2.5rem;'>
            <div class='floating' style='font-size: 2.5rem; margin-bottom: 1rem; color: var(--primary);'>⏱️</div>
            <h3 style='color: var(--primary); font-family: Poppins; font-weight: 700; font-size: 1.5rem; margin-bottom: 0.5rem;'>TIME TRACKER PRO</h3>
            <p style='color: var(--gray); font-size: 0.875rem;'>Professional Attendance Management</p>
        </div>
    """, unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title="",
        options=["USER PORTAL", "ADMIN DASHBOARD"],
        icons=["person-circle", "gear-fill"],
        menu_icon="",
        default_index=0,
        styles={
            "container": {
                "padding": "0!important", 
                "background-color": "transparent",
                "border": "none"
            },
            "icon": {"color": "var(--primary)", "font-size": "18px"},
            "nav-link": {
                "font-size": "15px",
                "text-align": "left",
                "margin": "4px 0",
                "padding": "1rem 1.5rem",
                "--hover-color": "rgba(37, 99, 235, 0.1)",
                "border-radius": "12px",
                "font-family": "Inter, sans-serif",
                "font-weight": "500",
                "color": "var(--gray)",
                "border": "1px solid transparent",
                "transition": "all 0.3s ease"
            },
            "nav-link-selected": {
                "background": "rgba(37, 99, 235, 0.15)",
                "border": "1px solid var(--primary)",
                "color": "var(--primary-light)",
                "font-weight": "600",
                "box-shadow": "var(--shadow)"
            },
        }
    )

# User Portal
if selected == "USER PORTAL":
    st.markdown("<h1 class='professional-header'>TIME TRACKER PRO</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1.5rem; font-family: Poppins;'>USER AUTHENTICATION</h3>", unsafe_allow_html=True)
        
        active_users = sorted(df[df['Active'] == True]['User'].unique().tolist())
        
        with st.form(key="user_selection_form"):
            if not active_users:
                st.markdown("<p class='status-inactive'>No active users available. Please contact the administrator.</p>", unsafe_allow_html=True)
                user_name = None
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    user_name = st.selectbox("SELECT USER", options=active_users, placeholder="Choose User...", key="user_select")
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    submitted = st.form_submit_button("ACTIVATE", use_container_width=True, type="primary")
                
                if submitted:
                    if user_name:
                        st.session_state.selected_user = user_name
                        st.session_state.last_action = f"User {user_name} activated"
                        st.rerun()
                    else:
                        st.error("Please select a user before submitting.")
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.selected_user:
        user_name = st.session_state.selected_user
        user_records = df[df['User'] == user_name]
        user_active = user_records['Active'].any() if not user_records.empty else True
        
        if not user_active:
            st.error("ACCESS DENIED: User account has been deactivated.")
            st.session_state.selected_user = None
        else:
            shift_date = get_shift_date()
            user_rows = df[(df['User'] == user_name) & (df['Date'] == str(shift_date))]
            
            # Start New Session
            col1, col2, col3 = st.columns([2, 1, 2])
            with col2:
                if st.button("START NEW SESSION", use_container_width=True, key="start_session", type="primary"):
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
                    st.success("Session initialized successfully")
                    st.rerun()

            if not user_rows.empty:
                row_index = user_rows.index[-1]
                
                # Action Buttons Grid
                st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                st.markdown("<h3 style='color: var(--light); text-align: center; margin-bottom: 1.5rem; font-family: Poppins;'>SESSION CONTROLS</h3>", unsafe_allow_html=True)
                
                # Main actions
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.button("CHECK IN", use_container_width=True, key=f"check_in_{row_index}", type="primary") and pd.isna(df.at[row_index, 'CheckIn']):
                        df.at[row_index, 'CheckIn'] = format_time(datetime.now(EGYPT_TZ))
                        total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                        df.at[row_index, 'TotalHours'] = total_hours
                        df.at[row_index, 'BreakDuration'] = break_duration
                        save_data()
                        st.session_state.last_action = "Checked in"
                        st.rerun()
                
                with col2:
                    for i in range(1, 4):
                        if st.button(f"BREAK {i} START", use_container_width=True, key=f"break_{i}_start_{row_index}") and pd.isna(df.at[row_index, f'Break{i}Start']) and pd.notna(df.at[row_index, 'CheckIn']):
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
                        if st.button(f"BREAK {i} END", use_container_width=True, key=f"break_{i}_end_{row_index}") and pd.notna(df.at[row_index, f'Break{i}Start']) and pd.isna(df.at[row_index, f'Break{i}End']):
                            df.at[row_index, f'Break{i}End'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = f"Break {i} ended"
                            st.rerun()
                    
                    if st.button("CHECK OUT", use_container_width=True, key=f"check_out_{row_index}", type="primary") and pd.notna(df.at[row_index, 'CheckIn']) and pd.isna(df.at[row_index, 'CheckOut']):
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
                st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                st.markdown("<h3 style='color: var(--light); margin-bottom: 1.5rem; font-family: Poppins;'>CURRENT SESSION STATUS</h3>", unsafe_allow_html=True)
                
                # Session metrics
                cols = st.columns(4)
                
                with cols[0]:
                    check_in_status = "Pending" if pd.isna(df.at[row_index, 'CheckIn']) else df.at[row_index, 'CheckIn']
                    st.metric("Check In", check_in_status)
                
                with cols[1]:
                    check_out_status = "Pending" if pd.isna(df.at[row_index, 'CheckOut']) else df.at[row_index, 'CheckOut']
                    st.metric("Check Out", check_out_status)
                
                with cols[2]:
                    st.metric("Total Hours", f"{df.at[row_index, 'TotalHours']:.1f}h")
                
                with cols[3]:
                    st.metric("Break Duration", f"{df.at[row_index, 'BreakDuration']:.1f}h")
                
                # Break status
                st.markdown("---")
                st.markdown("<h4 style='color: var(--gray); margin-top: 1rem;'>BREAK STATUS</h4>", unsafe_allow_html=True)
                
                break_cols = st.columns(3)
                for i in range(1, 4):
                    with break_cols[i-1]:
                        break_start = df.at[row_index, f'Break{i}Start']
                        break_end = df.at[row_index, f'Break{i}End']
                        
                        if pd.isna(break_start):
                            status_text = "Not Started"
                            status_color = "var(--gray)"
                        elif pd.notna(break_start) and pd.isna(break_end):
                            status_text = "Active"
                            status_color = "var(--warning)"
                        else:
                            status_text = "Completed"
                            status_color = "var(--success)"
                        
                        st.markdown(f"""
                            <div style='padding: 1rem; background: rgba(255,255,255,0.03); border-radius: 8px; border-left: 4px solid {status_color};'>
                                <div style='font-weight: 600; margin-bottom: 0.5rem;'>Break {i}</div>
                                <div style='font-size: 0.875rem; color: {status_color};'>{status_text}</div>
                                <div style='font-size: 0.75rem; color: var(--gray); margin-top: 0.5rem;'>
                                    {break_start if pd.notna(break_start) else '-'} 
                                    → 
                                    {break_end if pd.notna(break_end) else '-'}
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)

# Admin Dashboard
elif selected == "ADMIN DASHBOARD":
    st.markdown("<h1 class='professional-header'>ADMINISTRATOR DASHBOARD</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        admin_password = st.text_input("ENTER ADMIN PASSWORD", type="password", placeholder="Secure access key...")
        st.markdown("</div>", unsafe_allow_html=True)
    
    if admin_password == "admin123":
        
        # Data Restoration Section
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1rem;'>DATA RESTORATION</h3>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Upload Excel file to restore data", type=["xlsx"])
        if uploaded_file:
            if restore_from_excel(uploaded_file):
                st.success("Data restored successfully!")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Editor Section
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1rem;'>DATA EDITOR</h3>", unsafe_allow_html=True)
        
        # Filter options
        col1, col2 = st.columns(2)
        with col1:
            filter_user = st.selectbox("Filter by User", options=['All'] + sorted(df['User'].unique().tolist()), key='filter_user')
        with col2:
            filter_date = st.selectbox("Filter by Date", options=['All'] + sorted(df['Date'].dt.strftime('%Y-%m-%d').unique().tolist()), key='filter_date')
        
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
            if pd.notna(row['Date']):
                total_hours, break_duration = calculate_times(row, row['Date'].date())
                filtered_df.at[idx, 'TotalHours'] = total_hours
                filtered_df.at[idx, 'BreakDuration'] = break_duration
        
        # Editable DataFrame
        edited_df = st.data_editor(
            filtered_df,
            column_config={
                "User": st.column_config.TextColumn("User", width="medium"),
                "Date": st.column_config.DateColumn("Date", width="small"),
                "CheckIn": st.column_config.TextColumn("Check In", width="small", help="Format: HH:MM AM/PM"),
                "CheckOut": st.column_config.TextColumn("Check Out", width="small"),
                "Break1Start": st.column_config.TextColumn("Break 1 Start", width="small"),
                "Break1End": st.column_config.TextColumn("Break 1 End", width="small"),
                "Break2Start": st.column_config.TextColumn("Break 2 Start", width="small"),
                "Break2End": st.column_config.TextColumn("Break 2 End", width="small"),
                "Break3Start": st.column_config.TextColumn("Break 3 Start", width="small"),
                "Break3End": st.column_config.TextColumn("Break 3 End", width="small"),
                "TotalHours": st.column_config.NumberColumn("Total Hours", width="small", format="%.2f"),
                "BreakDuration": st.column_config.NumberColumn("Break Duration", width="small", format="%.2f"),
                "Active": st.column_config.CheckboxColumn("Active", width="small")
            },
            use_container_width=True,
            height=400,
            num_rows="dynamic"
        )
        
        if st.button("SAVE CHANGES", use_container_width=True, type="primary"):
            # Update calculations for edited rows
            for idx, row in edited_df.iterrows():
                if pd.notna(row['Date']):
                    total_hours, break_duration = calculate_times(row, row['Date'].date())
                    edited_df.at[idx, 'TotalHours'] = total_hours
                    edited_df.at[idx, 'BreakDuration'] = break_duration
            
            # Ensure data types
            for col in TIME_COLUMNS:
                edited_df[col] = edited_df[col].astype("string").fillna(pd.NA)
            
            edited_df['Active'] = edited_df['Active'].apply(to_boolean).astype("boolean")
            
            # Update main dataframe
            df.loc[edited_df.index] = edited_df
            
            if save_data():
                st.success("Data updated successfully!")
                st.session_state.last_action = "Data matrix updated"
                st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Analytics Section
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1rem;'>ANALYTICS DASHBOARD</h3>", unsafe_allow_html=True)
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_users = df['User'].nunique()
            st.metric("Total Users", total_users)
        
        with col2:
            active_users = df[df['Active'] == True]['User'].nunique()
            st.metric("Active Users", active_users)
        
        with col3:
            total_hours = df['TotalHours'].sum()
            st.metric("Total Hours", f"{total_hours:.0f}h")
        
        with col4:
            avg_hours = df['TotalHours'].mean() if not df.empty else 0
            st.metric("Avg Hours/User", f"{avg_hours:.1f}h")
        
        st.markdown("---")
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            # Hours per user
            if not df.empty:
                user_hours = df.groupby('User')['TotalHours'].sum().reset_index()
                if not user_hours.empty:
                    fig_bar = px.bar(
                        user_hours.nlargest(10, 'TotalHours'), 
                        x='User', 
                        y='TotalHours',
                        title='Top 10 Users by Total Hours',
                        color='TotalHours',
                        color_continuous_scale='Viridis'
                    )
                    fig_bar.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff',
                        showlegend=False,
                        margin=dict(t=30, b=20, l=20, r=20)
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
        
        with col2:
            # Daily trend
            if not df.empty and 'Date' in df.columns:
                daily_hours = df.groupby(df['Date'].dt.date)['TotalHours'].sum().reset_index()
                if not daily_hours.empty:
                    fig_line = px.line(
                        daily_hours.tail(30), 
                        x='Date', 
                        y='TotalHours',
                        title='Daily Hours Trend (Last 30 Days)',
                        markers=True
                    )
                    fig_line.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff',
                        showlegend=False,
                        margin=dict(t=30, b=20, l=20, r=20)
                    )
                    fig_line.update_traces(line_color='#3b82f6')
                    st.plotly_chart(fig_line, use_container_width=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # User Management
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1rem;'>USER MANAGEMENT</h3>", unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["ADD USER", "EDIT USER", "USER ACTIONS"])
        
        with tab1:
            st.markdown("<h4 style='color: var(--light); margin-bottom: 1rem;'>Add New User</h4>", unsafe_allow_html=True)
            new_user = st.text_input("User Name", placeholder="Enter new user name...")
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("ADD USER", use_container_width=True, type="primary") and new_user:
                    if new_user in df['User'].values:
                        st.warning(f"User '{new_user}' already exists.")
                    else:
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
                        new_row_df = pd.DataFrame([new_row])
                        df = pd.concat([df, new_row_df], ignore_index=True)
                        save_data()
                        st.success(f"User '{new_user}' added successfully!")
                        st.session_state.last_action = f"User {new_user} added"
                        st.rerun()
        
        with tab2:
            st.markdown("<h4 style='color: var(--light); margin-bottom: 1rem;'>Edit User Information</h4>", unsafe_allow_html=True)
            edit_user = st.selectbox("Select User", options=['Select...'] + sorted(df['User'].unique().tolist()), key='edit_user_select')
            
            if edit_user != 'Select...':
                user_data = df[df['User'] == edit_user]
                if not user_data.empty:
                    with st.form(key=f"edit_user_form"):
                        current_status = user_data.iloc[0]['Active']
                        new_status = st.checkbox("Active", value=current_status)
                        
                        if st.form_submit_button("UPDATE USER", type="primary"):
                            df.loc[df['User'] == edit_user, 'Active'] = new_status
                            save_data()
                            st.success(f"User '{edit_user}' updated successfully!")
                            st.session_state.last_action = f"User {edit_user} updated"
                            st.rerun()
        
        with tab3:
            st.markdown("<h4 style='color: var(--light); margin-bottom: 1rem;'>User Actions</h4>", unsafe_allow_html=True)
            action_user = st.selectbox("Select User for Action", options=['Select...'] + sorted(df['User'].unique().tolist()), key='action_user')
            action = st.selectbox("Select Action", 
                                options=['Select action...', 'Deactivate User', 'Reactivate User', 'Remove User Data'], 
                                key='user_action')
            
            if st.button("EXECUTE ACTION", use_container_width=True, type="primary") and action_user != 'Select...' and action != 'Select action...':
                if action == 'Deactivate User':
                    df.loc[df['User'] == action_user, 'Active'] = False
                    save_data()
                    st.success(f"User '{action_user}' deactivated.")
                
                elif action == 'Reactivate User':
                    df.loc[df['User'] == action_user, 'Active'] = True
                    save_data()
                    st.success(f"User '{action_user}' reactivated.")
                
                elif action == 'Remove User Data':
                    df = df[df['User'] != action_user]
                    save_data()
                    st.success(f"All data for user '{action_user}' removed.")
                
                st.session_state.last_action = f"Action '{action}' executed for user {action_user}"
                st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Export
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--light); margin-bottom: 1rem;'>DATA EXPORT</h3>", unsafe_allow_html=True)
        
        def get_excel_download_link(df):
            df_download = df.copy()
            df_download['Date'] = df_download['Date'].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
            )
            with pd.ExcelWriter('attendance_data.xlsx', engine='xlsxwriter') as writer:
                df_download.to_excel(writer, index=False, sheet_name='AttendanceData')
                # Add summary sheet
                summary = pd.DataFrame({
                    'Metric': ['Total Users', 'Active Users', 'Total Hours', 'Average Hours'],
                    'Value': [
                        df['User'].nunique(),
                        df[df['Active'] == True]['User'].nunique(),
                        f"{df['TotalHours'].sum():.1f}",
                        f"{df['TotalHours'].mean():.1f}" if not df.empty else "0.0"
                    ]
                })
                summary.to_excel(writer, index=False, sheet_name='Summary')
            
            with open('attendance_data.xlsx', 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode()
            
            return f'''
            <div style="text-align: center;">
                <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" 
                   download="attendance_data.xlsx"
                   style="display: inline-block;
                          padding: 0.875rem 2rem;
                          background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
                          color: white;
                          text-decoration: none;
                          border-radius: 12px;
                          font-weight: 600;
                          font-family: 'Inter', sans-serif;
                          transition: all 0.3s ease;
                          border: none;
                          cursor: pointer;">
                    DOWNLOAD DATA
                </a>
            </div>
            '''
        
        st.markdown(get_excel_download_link(df), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    else:
        if admin_password:
            st.error("Invalid password. Access denied.")

# Add action notification
if st.session_state.last_action:
    st.toast(f"{st.session_state.last_action}", icon="✅")
    st.session_state.last_action = None

# Real-time clock in sidebar
current_time = datetime.now(EGYPT_TZ).strftime("%Y-%m-%d %I:%M:%S %p")
st.sidebar.markdown(f"""
    <div class='glass-card' style='margin-top: 2rem; text-align: center;'>
        <div style='font-size: 0.8rem; color: var(--gray); letter-spacing: 1px; text-transform: uppercase; margin-bottom: 0.5rem;'>Current Time</div>
        <div style='font-family: "JetBrains Mono", monospace; font-size: 1rem; color: var(--light); font-weight: 500;'>{current_time}</div>
        <div style='font-size: 0.75rem; color: var(--gray); margin-top: 0.5rem;'>Cairo, Egypt</div>
    </div>
""", unsafe_allow_html=True)
