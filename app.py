import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
from streamlit_option_menu import option_menu
import streamlit.components.v1 as components
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import date

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
@st.cache_resource
def init_google_sheets():
    try:
        CREDS = get_credentials()
        if CREDS:
            CLIENT = gspread.authorize(CREDS)
            SHEET = CLIENT.open("AttendanceSheet").sheet1
            return SHEET
        else:
            return None
    except Exception as e:
        st.error(f"Error initializing Google Sheets: {str(e)}")
        return None

SHEET = init_google_sheets()

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
@st.cache_data(ttl=60)
def load_data():
    try:
        if SHEET is None:
            raise Exception("Google Sheets not initialized")
        
        data = SHEET.get_all_records()
        
        if not data:
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

# Function to save data to Google Sheets
def save_data():
    try:
        df_save = df.copy()
        df_save['Date'] = df_save['Date'].apply(
            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
        )
        
        # Convert all data to list format for Google Sheets
        values = [EXPECTED_COLUMNS] + df_save.fillna('').values.tolist()
        
        # Update the entire sheet at once
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
        
        # Remove duplicates
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

# PREMIUM CSS WITH ADVANCED ANIMATIONS AND 3D EFFECTS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

:root {
    --primary: #4361ee;
    --primary-dark: #3a56d4;
    --primary-light: #4895ef;
    --secondary: #7209b7;
    --accent: #4cc9f0;
    --success: #4ade80;
    --warning: #fbbf24;
    --danger: #f87171;
    --dark: #0f172a;
    --darker: #020617;
    --light: #f8fafc;
    --gray: #64748b;
    --gray-light: #e2e8f0;
    --glass: rgba(255, 255, 255, 0.08);
    --glass-border: rgba(255, 255, 255, 0.15);
    --glass-dark: rgba(15, 23, 42, 0.8);
    --shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
    --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
    --shadow-2xl: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body, .stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
    background-attachment: fixed;
    color: var(--light);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    overflow-x: hidden;
    min-height: 100vh;
    position: relative;
}

/* Animated Particle Background */
body::before {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: 
        radial-gradient(circle at 15% 20%, rgba(67, 97, 238, 0.25) 0%, transparent 40%),
        radial-gradient(circle at 85% 30%, rgba(114, 9, 183, 0.25) 0%, transparent 40%),
        radial-gradient(circle at 50% 80%, rgba(76, 201, 240, 0.2) 0%, transparent 40%),
        radial-gradient(circle at 70% 60%, rgba(244, 63, 94, 0.15) 0%, transparent 40%);
    z-index: -2;
    animation: particleFloat 20s ease-in-out infinite;
}

@keyframes particleFloat {
    0%, 100% { 
        transform: translate(0, 0) scale(1);
        opacity: 0.8;
    }
    33% { 
        transform: translate(-30px, 20px) scale(1.05);
        opacity: 1;
    }
    66% { 
        transform: translate(20px, -15px) scale(0.95);
        opacity: 0.6;
    }
}

/* Grid Overlay with Animation */
body::after {
    content: '';
    position: fixed;
    top: 0;
    left: 0;
    width: 200%;
    height: 200%;
    background: 
        linear-gradient(90deg, transparent 49.5%, rgba(255, 255, 255, 0.03) 49.5%, rgba(255, 255, 255, 0.03) 50.5%, transparent 50.5%),
        linear-gradient(0deg, transparent 49.5%, rgba(255, 255, 255, 0.03) 49.5%, rgba(255, 255, 255, 0.03) 50.5%, transparent 50.5%);
    background-size: 60px 60px;
    z-index: -1;
    opacity: 0.3;
    animation: gridMove 40s linear infinite;
    transform-origin: center;
}

@keyframes gridMove {
    0% { transform: translate(0, 0) rotate(0deg); }
    100% { transform: translate(-30px, -30px) rotate(0.5deg); }
}

/* Main container */
.main .block-container {
    padding-top: 3rem;
    padding-bottom: 5rem;
    max-width: 1600px;
    position: relative;
}

/* Premium Header with 3D Effect */
.premium-header {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 800;
    font-size: 3.5rem;
    text-align: center;
    margin-bottom: 3rem;
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 25%, var(--accent) 50%, var(--primary-light) 75%, var(--primary) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    background-size: 300% 300%;
    animation: gradientFlow 8s ease infinite, textFloat 6s ease-in-out infinite;
    position: relative;
    text-transform: uppercase;
    letter-spacing: 1px;
    filter: drop-shadow(0 10px 20px rgba(0, 0, 0, 0.3));
}

.premium-header::before {
    content: 'ATTENDANCE';
    position: absolute;
    top: 2px;
    left: 2px;
    background: linear-gradient(135deg, rgba(255,255,255,0.3) 0%, transparent 50%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    z-index: -1;
    opacity: 0.7;
}

.premium-header::after {
    content: '';
    position: absolute;
    bottom: -20px;
    left: 50%;
    transform: translateX(-50%);
    width: 200px;
    height: 4px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    border-radius: 2px;
    animation: lineGlow 2s ease-in-out infinite;
}

@keyframes gradientFlow {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
}

@keyframes textFloat {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-5px); }
}

@keyframes lineGlow {
    0%, 100% { 
        opacity: 0.5;
        box-shadow: 0 0 20px var(--accent);
    }
    50% { 
        opacity: 1;
        box-shadow: 0 0 40px var(--accent);
    }
}

/* Premium Glass Card with 3D Effect */
.premium-card {
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.1) 0%, 
        rgba(255, 255, 255, 0.05) 100%);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--glass-border);
    border-radius: 24px;
    padding: 2.5rem;
    margin: 2rem 0;
    position: relative;
    overflow: hidden;
    box-shadow: 
        var(--shadow-2xl),
        inset 0 1px 0 rgba(255, 255, 255, 0.1),
        0 20px 40px -20px rgba(0, 0, 0, 0.3);
    transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    animation: cardEntrance 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes cardEntrance {
    from {
        opacity: 0;
        transform: translateY(40px) scale(0.95) rotateX(10deg);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1) rotateX(0);
    }
}

.premium-card:hover {
    transform: translateY(-8px) scale(1.01);
    box-shadow: 
        var(--shadow-2xl),
        inset 0 1px 0 rgba(255, 255, 255, 0.2),
        0 30px 60px -30px rgba(0, 0, 0, 0.4),
        0 0 0 1px rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.3);
}

.premium-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(
        90deg,
        transparent,
        rgba(255, 255, 255, 0.1),
        rgba(255, 255, 255, 0.2),
        rgba(255, 255, 255, 0.1),
        transparent
    );
    transition: left 0.8s ease;
}

.premium-card:hover::before {
    left: 100%;
}

/* Premium Button with Glow Effect */
.stButton > button {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
    border: none !important;
    color: white !important;
    padding: 1rem 2rem !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    border-radius: 16px !important;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1) !important;
    position: relative !important;
    overflow: hidden !important;
    letter-spacing: 0.5px !important;
    box-shadow: 
        var(--shadow-lg),
        0 0 0 0 rgba(67, 97, 238, 0.7) !important;
    text-transform: uppercase !important;
}

.stButton > button:hover {
    background: linear-gradient(135deg, var(--primary-light) 0%, var(--primary) 100%) !important;
    transform: translateY(-3px) scale(1.05) !important;
    box-shadow: 
        var(--shadow-xl),
        0 10px 30px rgba(67, 97, 238, 0.4) !important;
}

.stButton > button:active {
    transform: translateY(-1px) scale(1.02) !important;
}

.stButton > button::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 0;
    height: 0;
    background: radial-gradient(circle, rgba(255,255,255,0.3) 0%, transparent 70%);
    border-radius: 50%;
    transform: translate(-50%, -50%);
    transition: width 0.6s, height 0.6s;
}

.stButton > button:active::after {
    width: 300px;
    height: 300px;
}

/* Secondary Button */
.secondary-btn .stButton > button {
    background: transparent !important;
    border: 2px solid var(--primary) !important;
    color: var(--primary) !important;
    box-shadow: none !important;
}

.secondary-btn .stButton > button:hover {
    background: rgba(67, 97, 238, 0.1) !important;
    border-color: var(--primary-light) !important;
    color: var(--primary-light) !important;
    box-shadow: 0 10px 30px rgba(67, 97, 238, 0.2) !important;
}

/* Success Button */
.success-btn .stButton > button {
    background: linear-gradient(135deg, var(--success) 0%, #22c55e 100%) !important;
}

.success-btn .stButton > button:hover {
    background: linear-gradient(135deg, #22c55e 0%, var(--success) 100%) !important;
    box-shadow: 
        var(--shadow-xl),
        0 10px 30px rgba(74, 222, 128, 0.4) !important;
}

/* Status Indicators with Pulse */
.status-badge {
    display: inline-block;
    padding: 0.5rem 1rem;
    border-radius: 20px;
    font-weight: 600;
    font-size: 0.875rem;
    letter-spacing: 0.5px;
    position: relative;
    overflow: hidden;
}

.status-active {
    background: linear-gradient(135deg, rgba(74, 222, 128, 0.2), rgba(74, 222, 128, 0.1));
    color: var(--success);
    border: 1px solid rgba(74, 222, 128, 0.3);
    animation: pulseSuccess 2s infinite;
}

.status-inactive {
    background: linear-gradient(135deg, rgba(248, 113, 113, 0.2), rgba(248, 113, 113, 0.1));
    color: var(--danger);
    border: 1px solid rgba(248, 113, 113, 0.3);
}

.status-pending {
    background: linear-gradient(135deg, rgba(251, 191, 36, 0.2), rgba(251, 191, 36, 0.1));
    color: var(--warning);
    border: 1px solid rgba(251, 191, 36, 0.3);
    animation: pulseWarning 2s infinite;
}

@keyframes pulseSuccess {
    0%, 100% { 
        box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.4);
    }
    70% { 
        box-shadow: 0 0 0 10px rgba(74, 222, 128, 0);
    }
}

@keyframes pulseWarning {
    0%, 100% { 
        box-shadow: 0 0 0 0 rgba(251, 191, 36, 0.4);
    }
    70% { 
        box-shadow: 0 0 0 10px rgba(251, 191, 36, 0);
    }
}

/* Enhanced Input Fields */
.stTextInput > div > div > input,
.stSelectbox > div > select,
.stDateInput > div > div > input,
.stTimeInput > div > div > input {
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.07) 0%, 
        rgba(255, 255, 255, 0.03) 100%) !important;
    border: 1px solid var(--glass-border) !important;
    color: var(--light) !important;
    border-radius: 14px !important;
    padding: 1rem 1.25rem !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 1rem !important;
    font-weight: 500 !important;
    transition: all 0.3s ease !important;
    backdrop-filter: blur(10px) !important;
}

.stTextInput > div > div > input:focus,
.stSelectbox > div > select:focus,
.stDateInput > div > div > input:focus,
.stTimeInput > div > div > input:focus {
    border-color: var(--primary-light) !important;
    box-shadow: 
        0 0 0 3px rgba(67, 97, 238, 0.2),
        0 10px 20px -10px rgba(67, 97, 238, 0.3) !important;
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.1) 0%, 
        rgba(255, 255, 255, 0.05) 100%) !important;
    transform: translateY(-1px);
}

/* Enhanced Dataframe */
.stDataFrame {
    border-radius: 16px !important;
    overflow: hidden !important;
}

.dataframe {
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.05) 0%, 
        rgba(255, 255, 255, 0.02) 100%) !important;
    backdrop-filter: blur(10px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 16px !important;
    overflow: hidden !important;
}

.dataframe th {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
    color: white !important;
    font-weight: 700 !important;
    border: none !important;
    padding: 1.25rem 1rem !important;
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
    font-size: 0.875rem !important;
}

.dataframe td {
    border-color: rgba(255, 255, 255, 0.05) !important;
    padding: 1rem !important;
    color: var(--light) !important;
    font-weight: 500 !important;
}

.dataframe tr:hover {
    background: rgba(255, 255, 255, 0.05) !important;
}

/* Enhanced Metrics */
.stMetric {
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.08) 0%, 
        rgba(255, 255, 255, 0.04) 100%);
    padding: 2rem;
    border-radius: 20px;
    border: 1px solid var(--glass-border);
    backdrop-filter: blur(10px);
    transition: all 0.3s ease;
}

.stMetric:hover {
    transform: translateY(-4px);
    border-color: var(--primary-light);
    box-shadow: var(--shadow-xl);
}

.stMetric label {
    color: var(--gray) !important;
    font-size: 0.875rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    margin-bottom: 0.5rem !important;
    font-family: 'Space Grotesk', sans-serif !important;
}

.stMetric value {
    color: var(--light) !important;
    font-size: 2.5rem !important;
    font-weight: 800 !important;
    font-family: 'Inter', sans-serif !important;
}

.stMetric delta {
    font-family: 'Plus Jakarta Sans', sans-serif !important;
    font-weight: 700 !important;
}

/* Enhanced Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 0.5rem;
    background: linear-gradient(135deg, 
        rgba(255, 255, 255, 0.05) 0%, 
        rgba(255, 255, 255, 0.02) 100%);
    padding: 0.5rem;
    border-radius: 16px;
    border: 1px solid var(--glass-border);
    backdrop-filter: blur(10px);
}

.stTabs [data-baseweb="tab"] {
    background: transparent;
    border-radius: 12px;
    padding: 1rem 2rem;
    font-weight: 600;
    color: var(--gray);
    transition: all 0.3s ease;
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 0.95rem;
}

.stTabs [data-baseweb="tab"]:hover {
    background: rgba(255, 255, 255, 0.05);
    color: var(--light);
}

.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
    color: white !important;
    font-weight: 700 !important;
    box-shadow: var(--shadow);
}

/* Enhanced Progress Bar */
.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--primary), var(--accent)) !important;
    border-radius: 10px !important;
    animation: progressGlow 2s ease-in-out infinite !important;
}

@keyframes progressGlow {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.8; }
}

/* Custom Scrollbar */
::-webkit-scrollbar {
    width: 12px;
    height: 12px;
}

::-webkit-scrollbar-track {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 6px;
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--primary), var(--secondary));
    border-radius: 6px;
    border: 2px solid transparent;
    background-clip: padding-box;
}

::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(180deg, var(--primary-light), var(--secondary));
}

/* Floating Elements Animation */
@keyframes float {
    0%, 100% { 
        transform: translateY(0px) rotate(0deg);
    }
    33% { 
        transform: translateY(-15px) rotate(1deg);
    }
    66% { 
        transform: translateY(10px) rotate(-1deg);
    }
}

.floating {
    animation: float 8s ease-in-out infinite;
}

/* Glowing Border Animation */
@keyframes borderGlow {
    0%, 100% { 
        border-color: rgba(67, 97, 238, 0.3);
        box-shadow: 0 0 20px rgba(67, 97, 238, 0.3);
    }
    50% { 
        border-color: rgba(76, 201, 240, 0.5);
        box-shadow: 0 0 40px rgba(76, 201, 240, 0.5);
    }
}

.glow-border {
    animation: borderGlow 3s ease-in-out infinite;
}

/* Shimmer Effect */
@keyframes shimmer {
    0% { background-position: -1000px 0; }
    100% { background-position: 1000px 0; }
}

.shimmer {
    background: linear-gradient(90deg, 
        rgba(255,255,255,0) 0%, 
        rgba(255,255,255,0.1) 50%, 
        rgba(255,255,255,0) 100%);
    background-size: 1000px 100%;
    animation: shimmer 3s infinite linear;
}

/* Sidebar Enhancement */
section[data-testid="stSidebar"] {
    background: linear-gradient(135deg, 
        rgba(15, 23, 42, 0.95) 0%, 
        rgba(30, 41, 59, 0.95) 100%);
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    backdrop-filter: blur(20px);
}

/* Divider */
hr {
    border: none;
    height: 1px;
    background: linear-gradient(90deg, 
        transparent, 
        var(--glass-border), 
        transparent);
    margin: 2rem 0;
}

/* Notification Toast */
.toast {
    background: linear-gradient(135deg, 
        rgba(15, 23, 42, 0.95) 0%, 
        rgba(30, 41, 59, 0.95) 100%) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid var(--glass-border) !important;
    border-radius: 16px !important;
    box-shadow: var(--shadow-2xl) !important;
    font-family: 'Inter', sans-serif !important;
}

/* Loading Spinner */
.stSpinner > div {
    border-color: var(--primary) !important;
    border-right-color: transparent !important;
}

/* Checkbox and Radio Styling */
.stCheckbox > label,
.stRadio > label {
    color: var(--light) !important;
    font-weight: 500 !important;
}

/* Card Title */
.card-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--light);
    margin-bottom: 1.5rem;
    position: relative;
    display: inline-block;
}

.card-title::after {
    content: '';
    position: absolute;
    bottom: -8px;
    left: 0;
    width: 60px;
    height: 3px;
    background: linear-gradient(90deg, var(--primary), var(--accent));
    border-radius: 2px;
}

/* Badge */
.badge {
    display: inline-block;
    padding: 0.25rem 0.75rem;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.badge-primary {
    background: linear-gradient(135deg, var(--primary), var(--primary-dark));
    color: white;
}

.badge-success {
    background: linear-gradient(135deg, var(--success), #22c55e);
    color: white;
}

.badge-warning {
    background: linear-gradient(135deg, var(--warning), #f59e0b);
    color: #0f172a;
}

.badge-danger {
    background: linear-gradient(135deg, var(--danger), #ef4444);
    color: white;
}

/* Tooltip */
.tooltip {
    position: relative;
    display: inline-block;
    cursor: help;
}

.tooltip .tooltiptext {
    visibility: hidden;
    width: 200px;
    background: linear-gradient(135deg, var(--dark), var(--darker));
    color: var(--light);
    text-align: center;
    padding: 0.75rem;
    border-radius: 12px;
    border: 1px solid var(--glass-border);
    position: absolute;
    z-index: 1000;
    bottom: 125%;
    left: 50%;
    transform: translateX(-50%);
    opacity: 0;
    transition: opacity 0.3s;
    font-size: 0.875rem;
    box-shadow: var(--shadow-xl);
    backdrop-filter: blur(10px);
}

.tooltip:hover .tooltiptext {
    visibility: visible;
    opacity: 1;
}

/* Alert Box */
.alert {
    padding: 1.25rem 1.5rem;
    border-radius: 16px;
    margin: 1rem 0;
    font-weight: 500;
    border: 1px solid;
    backdrop-filter: blur(10px);
}

.alert-success {
    background: linear-gradient(135deg, 
        rgba(74, 222, 128, 0.15), 
        rgba(74, 222, 128, 0.05));
    border-color: rgba(74, 222, 128, 0.3);
    color: var(--success);
}

.alert-warning {
    background: linear-gradient(135deg, 
        rgba(251, 191, 36, 0.15), 
        rgba(251, 191, 36, 0.05));
    border-color: rgba(251, 191, 36, 0.3);
    color: var(--warning);
}

.alert-danger {
    background: linear-gradient(135deg, 
        rgba(248, 113, 113, 0.15), 
        rgba(248, 113, 113, 0.05));
    border-color: rgba(248, 113, 113, 0.3);
    color: var(--danger);
}

.alert-info {
    background: linear-gradient(135deg, 
        rgba(67, 97, 238, 0.15), 
        rgba(67, 97, 238, 0.05));
    border-color: rgba(67, 97, 238, 0.3);
    color: var(--primary);
}

/* Section Divider */
.section-divider {
    height: 1px;
    background: linear-gradient(90deg, 
        transparent, 
        var(--glass-border), 
        var(--primary), 
        var(--glass-border), 
        transparent);
    margin: 2.5rem 0;
    position: relative;
}

.section-divider::before {
    content: '';
    position: absolute;
    top: -4px;
    left: 50%;
    transform: translateX(-50%);
    width: 8px;
    height: 8px;
    background: var(--primary);
    border-radius: 50%;
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { 
        box-shadow: 0 0 0 0 rgba(67, 97, 238, 0.7);
    }
    70% { 
        box-shadow: 0 0 0 10px rgba(67, 97, 238, 0);
    }
}

/* Avatar */
.avatar {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--primary), var(--secondary));
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 700;
    font-size: 1.25rem;
    box-shadow: var(--shadow);
}

/* Icon Box */
.icon-box {
    width: 60px;
    height: 60px;
    border-radius: 16px;
    background: linear-gradient(135deg, 
        rgba(67, 97, 238, 0.2), 
        rgba(67, 97, 238, 0.1));
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 1rem;
    border: 1px solid rgba(67, 97, 238, 0.3);
    transition: all 0.3s ease;
}

.icon-box:hover {
    transform: rotate(10deg) scale(1.1);
    background: linear-gradient(135deg, 
        rgba(67, 97, 238, 0.3), 
        rgba(67, 97, 238, 0.2));
    border-color: rgba(67, 97, 238, 0.5);
}
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None
if 'last_action' not in st.session_state:
    st.session_state.last_action = None
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "dashboard"
if 'stats_refresh' not in st.session_state:
    st.session_state.stats_refresh = datetime.now()

# Premium Sidebar Navigation
with st.sidebar:
    st.markdown("""
        <div style='text-align: center; margin-bottom: 3rem;'>
            <div class='floating' style='font-size: 3rem; margin-bottom: 1rem; color: var(--primary); background: linear-gradient(135deg, var(--primary), var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent;'>⏰</div>
            <h3 style='color: var(--primary); font-family: Space Grotesk; font-weight: 800; font-size: 1.75rem; margin-bottom: 0.5rem; letter-spacing: 1px;'>ATTENDANCE PRO</h3>
            <p style='color: var(--gray); font-size: 0.875rem; letter-spacing: 0.5px; font-weight: 500;'>Professional Workforce Management</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Statistics in Sidebar
    if not df.empty:
        col1, col2 = st.columns(2)
        with col1:
            total_active = df[df['Active'] == True]['User'].nunique()
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, rgba(67, 97, 238, 0.2), rgba(67, 97, 238, 0.1)); padding: 1rem; border-radius: 16px; text-align: center; border: 1px solid rgba(67, 97, 238, 0.3);'>
                    <div style='font-size: 0.75rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem;'>Active</div>
                    <div style='font-size: 1.5rem; font-weight: 800; color: var(--primary);'>{total_active}</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            today = pd.Timestamp.now().date()
            today_attendance = len(df[df['Date'].dt.date == today])
            st.markdown(f"""
                <div style='background: linear-gradient(135deg, rgba(76, 201, 240, 0.2), rgba(76, 201, 240, 0.1)); padding: 1rem; border-radius: 16px; text-align: center; border: 1px solid rgba(76, 201, 240, 0.3);'>
                    <div style='font-size: 0.75rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem;'>Today</div>
                    <div style='font-size: 1.5rem; font-weight: 800; color: var(--accent);'>{today_attendance}</div>
                </div>
            """, unsafe_allow_html=True)
    
    st.markdown("<div class='section-divider' style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title="",
        options=["DASHBOARD", "USER PORTAL", "ADMIN PANEL"],
        icons=["speedometer2", "person-badge", "shield-lock"],
        menu_icon="",
        default_index=0,
        styles={
            "container": {
                "padding": "0!important", 
                "background-color": "transparent",
                "border": "none"
            },
            "icon": {"color": "var(--primary)", "font-size": "20px"},
            "nav-link": {
                "font-size": "16px",
                "text-align": "left",
                "margin": "8px 0",
                "padding": "1.25rem 1.5rem",
                "--hover-color": "rgba(67, 97, 238, 0.1)",
                "border-radius": "16px",
                "font-family": "Plus Jakarta Sans, sans-serif",
                "font-weight": "600",
                "color": "var(--gray)",
                "border": "1px solid transparent",
                "transition": "all 0.3s ease"
            },
            "nav-link-selected": {
                "background": "linear-gradient(135deg, rgba(67, 97, 238, 0.2), rgba(67, 97, 238, 0.1))",
                "border": "1px solid var(--primary)",
                "color": "var(--primary-light)",
                "font-weight": "700",
                "box-shadow": "var(--shadow)"
            },
        }
    )
    
    # Real-time clock
    current_time = datetime.now(EGYPT_TZ).strftime("%I:%M %p")
    current_date = datetime.now(EGYPT_TZ).strftime("%B %d, %Y")
    st.markdown(f"""
        <div style='margin-top: 3rem; padding: 1.5rem; background: linear-gradient(135deg, rgba(15, 23, 42, 0.8), rgba(30, 41, 59, 0.8)); border-radius: 20px; border: 1px solid var(--glass-border); backdrop-filter: blur(10px);'>
            <div style='text-align: center;'>
                <div style='font-family: Space Grotesk; font-size: 2rem; font-weight: 700; color: var(--primary); margin-bottom: 0.5rem;'>{current_time}</div>
                <div style='font-size: 0.875rem; color: var(--gray); font-weight: 500;'>{current_date}</div>
                <div style='font-size: 0.75rem; color: var(--gray); margin-top: 0.5rem; font-weight: 500;'>Cairo, Egypt • GMT+2</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

# Dashboard
if selected == "DASHBOARD":
    st.markdown("<h1 class='premium-header'>ATTENDANCE</h1>", unsafe_allow_html=True)
    
    # Quick Stats Cards
    st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
    st.markdown("<h3 class='card-title'>Overview Dashboard</h3>", unsafe_allow_html=True)
    
    if df.empty:
        st.markdown("""
            <div class='alert alert-info'>
                No attendance data available. Start by adding users and recording attendance.
            </div>
        """, unsafe_allow_html=True)
    else:
        # Calculate statistics
        total_users = df['User'].nunique()
        active_users = df[df['Active'] == True]['User'].nunique()
        total_hours = df['TotalHours'].sum()
        avg_hours = df['TotalHours'].mean() if len(df) > 0 else 0
        today = pd.Timestamp.now().date()
        today_attendance = len(df[df['Date'].dt.date == today])
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
                <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(67, 97, 238, 0.15), rgba(67, 97, 238, 0.05)); border-radius: 20px; border: 1px solid rgba(67, 97, 238, 0.3);'>
                    <div style='font-size: 2.5rem; font-weight: 800; color: var(--primary); margin-bottom: 0.5rem;'>{total_users}</div>
                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>Total Users</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(74, 222, 128, 0.15), rgba(74, 222, 128, 0.05)); border-radius: 20px; border: 1px solid rgba(74, 222, 128, 0.3);'>
                    <div style='font-size: 2.5rem; font-weight: 800; color: var(--success); margin-bottom: 0.5rem;'>{active_users}</div>
                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>Active Users</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
                <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(76, 201, 240, 0.15), rgba(76, 201, 240, 0.05)); border-radius: 20px; border: 1px solid rgba(76, 201, 240, 0.3);'>
                    <div style='font-size: 2.5rem; font-weight: 800; color: var(--accent); margin-bottom: 0.5rem;'>{total_hours:.0f}</div>
                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>Total Hours</div>
                </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
                <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(251, 191, 36, 0.15), rgba(251, 191, 36, 0.05)); border-radius: 20px; border: 1px solid rgba(251, 191, 36, 0.3);'>
                    <div style='font-size: 2.5rem; font-weight: 800; color: var(--warning); margin-bottom: 0.5rem;'>{today_attendance}</div>
                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>Today's Attendance</div>
                </div>
            """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Charts Section
    if not df.empty:
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<h3 class='card-title'>Analytics & Insights</h3>", unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["📈 Performance", "👥 User Analysis", "📅 Monthly Trends"])
        
        with tab1:
            col1, col2 = st.columns(2)
            
            with col1:
                # Top performers by hours
                top_users = df.groupby('User')['TotalHours'].sum().nlargest(10).reset_index()
                fig1 = px.bar(
                    top_users, 
                    x='TotalHours', 
                    y='User',
                    orientation='h',
                    title='Top 10 Performers (Total Hours)',
                    color='TotalHours',
                    color_continuous_scale='Viridis'
                )
                fig1.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#ffffff',
                    showlegend=False,
                    height=400
                )
                st.plotly_chart(fig1, use_container_width=True)
            
            with col2:
                # Attendance distribution
                if 'Date' in df.columns:
                    daily_counts = df.groupby(df['Date'].dt.date).size().reset_index(name='Count')
                    fig2 = px.line(
                        daily_counts.tail(30),
                        x='Date',
                        y='Count',
                        title='Daily Attendance (Last 30 Days)',
                        markers=True
                    )
                    fig2.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff',
                        showlegend=False,
                        height=400
                    )
                    fig2.update_traces(line_color='#4cc9f0', line_width=3)
                    st.plotly_chart(fig2, use_container_width=True)
        
        with tab2:
            # User statistics
            user_stats = df.groupby('User').agg({
                'TotalHours': 'sum',
                'Active': 'last'
            }).reset_index()
            
            fig3 = px.scatter(
                user_stats,
                x='User',
                y='TotalHours',
                size='TotalHours',
                color='Active',
                title='User Performance Distribution',
                hover_name='User',
                size_max=50
            )
            fig3.update_layout(
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font_color='#ffffff',
                height=400
            )
            st.plotly_chart(fig3, use_container_width=True)
        
        with tab3:
            # Monthly trends
            if 'Date' in df.columns:
                df['Month'] = df['Date'].dt.to_period('M').astype(str)
                monthly_stats = df.groupby('Month').agg({
                    'TotalHours': 'sum',
                    'User': 'nunique'
                }).reset_index()
                
                fig4 = make_subplots(specs=[[{"secondary_y": True}]])
                
                fig4.add_trace(
                    go.Bar(
                        x=monthly_stats['Month'],
                        y=monthly_stats['TotalHours'],
                        name='Total Hours',
                        marker_color='#4361ee'
                    ),
                    secondary_y=False
                )
                
                fig4.add_trace(
                    go.Scatter(
                        x=monthly_stats['Month'],
                        y=monthly_stats['User'],
                        name='Active Users',
                        mode='lines+markers',
                        line=dict(color='#4cc9f0', width=3)
                    ),
                    secondary_y=True
                )
                
                fig4.update_layout(
                    title='Monthly Trends',
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#ffffff',
                    height=400
                )
                
                st.plotly_chart(fig4, use_container_width=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Recent Activity
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<h3 class='card-title'>Recent Activity</h3>", unsafe_allow_html=True)
        
        recent_activity = df.sort_values('Date', ascending=False).head(10)
        st.dataframe(
            recent_activity[['User', 'Date', 'CheckIn', 'CheckOut', 'TotalHours', 'Active']],
            use_container_width=True,
            hide_index=True
        )
        
        st.markdown("</div>", unsafe_allow_html=True)

# User Portal
elif selected == "USER PORTAL":
    st.markdown("<h1 class='premium-header'>ATTENDANCE</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<h3 class='card-title'>User Authentication</h3>", unsafe_allow_html=True)
        
        active_users = sorted(df[df['Active'] == True]['User'].unique().tolist())
        
        with st.form(key="user_selection_form"):
            if not active_users:
                st.markdown("""
                    <div class='alert alert-warning'>
                        No active users available. Please contact the administrator.
                    </div>
                """, unsafe_allow_html=True)
                user_name = None
            else:
                col1, col2 = st.columns([3, 1])
                with col1:
                    user_name = st.selectbox(
                        "Select Your Identity",
                        options=active_users,
                        placeholder="Choose User...",
                        key="user_select"
                    )
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    submitted = st.form_submit_button(
                        "ACTIVATE",
                        use_container_width=True,
                        type="primary"
                    )
                
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
            st.markdown("""
                <div class='alert alert-danger'>
                    <strong>ACCESS DENIED</strong><br>
                    Your account has been deactivated. Please contact the administrator.
                </div>
            """, unsafe_allow_html=True)
            st.session_state.selected_user = None
        else:
            shift_date = get_shift_date()
            user_rows = df[(df['User'] == user_name) & (df['Date'] == str(shift_date))]
            
            # Welcome Header
            st.markdown(f"""
                <div class='premium-card' style='text-align: center;'>
                    <div style='display: flex; align-items: center; justify-content: center; gap: 1rem; margin-bottom: 1.5rem;'>
                        <div class='avatar'>{user_name[0].upper()}</div>
                        <div style='text-align: left;'>
                            <h3 style='color: var(--light); margin-bottom: 0.25rem; font-family: Space Grotesk;'>Welcome, {user_name}</h3>
                            <div style='font-size: 0.875rem; color: var(--gray);'>Today's Date: {shift_date}</div>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            
            # Start New Session
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
                st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
                st.markdown("<h3 class='card-title'>Session Controls</h3>", unsafe_allow_html=True)
                
                # Main actions in a grid
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.button("CHECK IN", 
                               use_container_width=True, 
                               key=f"check_in_{row_index}", 
                               type="primary",
                               disabled=pd.notna(df.at[row_index, 'CheckIn'])):
                        if pd.isna(df.at[row_index, 'CheckIn']):
                            df.at[row_index, 'CheckIn'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = "Checked in"
                            st.rerun()
                
                with col2:
                    for i in range(1, 4):
                        break_disabled = not (
                            pd.isna(df.at[row_index, f'Break{i}Start']) and 
                            pd.notna(df.at[row_index, 'CheckIn']) and
                            (i == 1 or pd.notna(df.at[row_index, f'Break{i-1}End']))
                        )
                        
                        if st.button(f"BREAK {i} START", 
                                   use_container_width=True, 
                                   key=f"break_{i}_start_{row_index}",
                                   disabled=break_disabled):
                            df.at[row_index, f'Break{i}Start'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = f"Break {i} started"
                            st.rerun()
                
                with col3:
                    for i in range(1, 4):
                        end_disabled = not (
                            pd.notna(df.at[row_index, f'Break{i}Start']) and 
                            pd.isna(df.at[row_index, f'Break{i}End'])
                        )
                        
                        if st.button(f"BREAK {i} END", 
                                   use_container_width=True, 
                                   key=f"break_{i}_end_{row_index}",
                                   disabled=end_disabled):
                            df.at[row_index, f'Break{i}End'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.session_state.last_action = f"Break {i} ended"
                            st.rerun()
                    
                    checkout_disabled = not (
                        pd.notna(df.at[row_index, 'CheckIn']) and 
                        pd.isna(df.at[row_index, 'CheckOut']) and
                        all(pd.notna(df.at[row_index, f'Break{i}End']) for i in range(1, 4) 
                            if pd.notna(df.at[row_index, f'Break{i}Start']))
                    )
                    
                    if st.button("CHECK OUT", 
                               use_container_width=True, 
                               key=f"check_out_{row_index}",
                               type="primary",
                               disabled=checkout_disabled):
                        df.at[row_index, 'CheckOut'] = format_time(datetime.now(EGYPT_TZ))
                        total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                        df.at[row_index, 'TotalHours'] = total_hours
                        df.at[row_index, 'BreakDuration'] = break_duration
                        save_data()
                        st.session_state.last_action = "Checked out"
                        st.rerun()
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                # Current Session Status
                st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
                st.markdown("<h3 class='card-title'>Current Session Status</h3>", unsafe_allow_html=True)
                
                # Session metrics in a grid
                col1, col2, col3, col4 = st.columns(4)
                
                session_data = [
                    ("Check In", df.at[row_index, 'CheckIn'], "var(--primary)"),
                    ("Check Out", df.at[row_index, 'CheckOut'], "var(--accent)"),
                    ("Total Hours", f"{df.at[row_index, 'TotalHours']:.1f}h", "var(--success)"),
                    ("Break Duration", f"{df.at[row_index, 'BreakDuration']:.1f}h", "var(--warning)")
                ]
                
                for i, (label, value, color) in enumerate(session_data):
                    with [col1, col2, col3, col4][i]:
                        st.markdown(f"""
                            <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)); border-radius: 16px; border: 1px solid var(--glass-border);'>
                                <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.75rem;'>{label}</div>
                                <div style='font-size: 1.75rem; font-weight: 800; color: {color};'>{value if pd.notna(value) else '-'}</div>
                            </div>
                        """, unsafe_allow_html=True)
                
                # Break status
                st.markdown("<div class='section-divider' style='margin: 2rem 0;'></div>", unsafe_allow_html=True)
                st.markdown("<h4 style='color: var(--gray); margin-bottom: 1.5rem;'>Break Schedule</h4>", unsafe_allow_html=True)
                
                break_cols = st.columns(3)
                for i in range(1, 4):
                    with break_cols[i-1]:
                        break_start = df.at[row_index, f'Break{i}Start']
                        break_end = df.at[row_index, f'Break{i}End']
                        
                        if pd.isna(break_start):
                            status = "Not Started"
                            color = "var(--gray)"
                            bg_color = "rgba(100, 116, 139, 0.1)"
                            border_color = "rgba(100, 116, 139, 0.3)"
                        elif pd.notna(break_start) and pd.isna(break_end):
                            status = "Active"
                            color = "var(--warning)"
                            bg_color = "rgba(251, 191, 36, 0.1)"
                            border_color = "rgba(251, 191, 36, 0.3)"
                        else:
                            status = "Completed"
                            color = "var(--success)"
                            bg_color = "rgba(74, 222, 128, 0.1)"
                            border_color = "rgba(74, 222, 128, 0.3)"
                        
                        st.markdown(f"""
                            <div style='padding: 1.5rem; background: {bg_color}; border-radius: 16px; border: 1px solid {border_color}; backdrop-filter: blur(10px);'>
                                <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;'>
                                    <div style='font-weight: 700; color: var(--light);'>Break {i}</div>
                                    <div class='status-badge' style='background: {bg_color}; color: {color}; border-color: {border_color};'>{status}</div>
                                </div>
                                <div style='margin-bottom: 0.75rem;'>
                                    <div style='font-size: 0.75rem; color: var(--gray); margin-bottom: 0.25rem;'>Start Time</div>
                                    <div style='font-weight: 600; color: var(--light);'>{break_start if pd.notna(break_start) else '--:-- --'}</div>
                                </div>
                                <div>
                                    <div style='font-size: 0.75rem; color: var(--gray); margin-bottom: 0.25rem;'>End Time</div>
                                    <div style='font-weight: 600; color: var(--light);'>{break_end if pd.notna(break_end) else '--:-- --'}</div>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
                
                # User Statistics
                user_stats = df[df['User'] == user_name]
                if not user_stats.empty:
                    total_user_hours = user_stats['TotalHours'].sum()
                    avg_daily_hours = user_stats['TotalHours'].mean()
                    total_days = user_stats['Date'].nunique()
                    
                    st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
                    st.markdown("<h3 class='card-title'>Your Statistics</h3>", unsafe_allow_html=True)
                    
                    stat_cols = st.columns(3)
                    stat_data = [
                        (f"{total_user_hours:.1f}", "Total Hours", "var(--primary)"),
                        (f"{avg_daily_hours:.1f}", "Avg Daily Hours", "var(--accent)"),
                        (str(total_days), "Days Tracked", "var(--success)")
                    ]
                    
                    for i, (value, label, color) in enumerate(stat_data):
                        with stat_cols[i]:
                            st.markdown(f"""
                                <div style='text-align: center; padding: 1.5rem; background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)); border-radius: 16px; border: 1px solid var(--glass-border);'>
                                    <div style='font-size: 2rem; font-weight: 800; color: {color}; margin-bottom: 0.5rem;'>{value}</div>
                                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>{label}</div>
                                </div>
                            """, unsafe_allow_html=True)
                    
                    st.markdown("</div>", unsafe_allow_html=True)

# Admin Panel
elif selected == "ADMIN PANEL":
    st.markdown("<h1 class='premium-header'>ATTENDANCE</h1>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<h3 class='card-title'>Administrator Access</h3>", unsafe_allow_html=True)
        
        admin_password = st.text_input(
            "Enter Administrator Password",
            type="password",
            placeholder="Secure access credentials...",
            help="Default password: admin123"
        )
        st.markdown("</div>", unsafe_allow_html=True)
    
    if admin_password == "admin123":
        st.success("Administrator access granted")
        
        # Data Management Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Data Editor", "👥 User Management", "📈 Analytics", "⚙️ System"])
        
        with tab1:
            st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
            st.markdown("<h3 class='card-title'>Data Editor</h3>", unsafe_allow_html=True)
            
            # Data Restoration
            with st.expander("Data Import & Export", expanded=False):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### Import Data")
                    uploaded_file = st.file_uploader(
                        "Upload Excel file to restore data", 
                        type=["xlsx"],
                        help="Upload an Excel file with attendance data"
                    )
                    if uploaded_file:
                        if restore_from_excel(uploaded_file):
                            st.rerun()
                
                with col2:
                    st.markdown("#### Export Data")
                    def get_excel_download_link(df):
                        df_download = df.copy()
                        df_download['Date'] = df_download['Date'].apply(
                            lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) and hasattr(x, 'strftime') else str(x) if pd.notna(x) else ''
                        )
                        with pd.ExcelWriter('attendance_export.xlsx', engine='xlsxwriter') as writer:
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
                        
                        with open('attendance_export.xlsx', 'rb') as f:
                            data = f.read()
                        b64 = base64.b64encode(data).decode()
                        return b64
                    
                    if not df.empty:
                        b64 = get_excel_download_link(df)
                        st.markdown(f"""
                            <a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" 
                               download="attendance_export.xlsx"
                               style="display: inline-block;
                                      padding: 0.875rem 2rem;
                                      background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
                                      color: white;
                                      text-decoration: none;
                                      border-radius: 16px;
                                      font-weight: 700;
                                      font-family: 'Plus Jakarta Sans', sans-serif;
                                      transition: all 0.3s ease;
                                      border: none;
                                      cursor: pointer;
                                      text-align: center;">
                                Download Data
                            </a>
                        """, unsafe_allow_html=True)
            
            # Filter options
            st.markdown("#### Filter Data")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                filter_user = st.selectbox(
                    "Filter by User",
                    options=['All Users'] + sorted(df['User'].unique().tolist()),
                    key='filter_user_admin'
                )
            
            with col2:
                filter_date = st.selectbox(
                    "Filter by Date",
                    options=['All Dates'] + sorted(df['Date'].dt.strftime('%Y-%m-%d').unique().tolist()),
                    key='filter_date_admin'
                )
            
            with col3:
                filter_status = st.selectbox(
                    "Filter by Status",
                    options=['All', 'Active Only', 'Inactive Only'],
                    key='filter_status_admin'
                )
            
            # Apply filters
            filtered_df = df
            if filter_user != 'All Users':
                filtered_df = filtered_df[filtered_df['User'] == filter_user]
            if filter_date != 'All Dates':
                filtered_df = filtered_df[filtered_df['Date'].dt.strftime('%Y-%m-%d') == filter_date]
            if filter_status == 'Active Only':
                filtered_df = filtered_df[filtered_df['Active'] == True]
            elif filter_status == 'Inactive Only':
                filtered_df = filtered_df[filtered_df['Active'] == False]
            
            # Editable DataFrame
            st.markdown("#### Edit Data")
            edited_df = st.data_editor(
                filtered_df,
                column_config={
                    "User": st.column_config.TextColumn("User", width="medium"),
                    "Date": st.column_config.DateColumn("Date", width="small"),
                    "CheckIn": st.column_config.TextColumn("Check In", width="small"),
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
                height=500,
                num_rows="dynamic"
            )
            
            if st.button("Save Changes", use_container_width=True, type="primary"):
                # Update calculations for edited rows
                for idx, row in edited_df.iterrows():
                    if pd.notna(row['Date']):
                        total_hours, break_duration = calculate_times(row, row['Date'].date())
                        edited_df.at[idx, 'TotalHours'] = total_hours
                        edited_df.at[idx, 'BreakDuration'] = break_duration
                
                # Update main dataframe
                df.loc[edited_df.index] = edited_df
                
                if save_data():
                    st.success("Data saved successfully!")
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with tab2:
            st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
            st.markdown("<h3 class='card-title'>User Management</h3>", unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### Add New User")
                with st.form(key="add_user_form"):
                    new_user = st.text_input("User Name", placeholder="Enter new user name...")
                    submit_add = st.form_submit_button("Add User", use_container_width=True, type="primary")
                    
                    if submit_add and new_user:
                        if new_user.strip():
                            if new_user not in df['User'].values:
                                new_row = {
                                    'User': new_user.strip(),
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
                                st.rerun()
                            else:
                                st.warning(f"User '{new_user}' already exists!")
            
            with col2:
                st.markdown("#### Manage Existing Users")
                user_list = sorted(df['User'].unique().tolist())
                
                if user_list:
                    selected_user = st.selectbox(
                        "Select User",
                        options=user_list,
                        key="manage_user_select"
                    )
                    
                    if selected_user:
                        user_data = df[df['User'] == selected_user]
                        current_status = user_data.iloc[0]['Active'] if not user_data.empty else True
                        
                        col_a, col_b = st.columns(2)
                        
                        with col_a:
                            new_status = st.checkbox("Active", value=current_status, key="user_status_check")
                        
                        with col_b:
                            if st.button("Update Status", use_container_width=True):
                                df.loc[df['User'] == selected_user, 'Active'] = new_status
                                save_data()
                                st.success(f"User '{selected_user}' status updated!")
                                st.rerun()
                        
                        if st.button("Remove User Data", use_container_width=True, type="secondary"):
                            df = df[df['User'] != selected_user]
                            save_data()
                            st.success(f"All data for user '{selected_user}' removed!")
                            st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with tab3:
            st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
            st.markdown("<h3 class='card-title'>Advanced Analytics</h3>", unsafe_allow_html=True)
            
            if not df.empty:
                # Detailed statistics
                st.markdown("#### Comprehensive Statistics")
                
                col1, col2, col3, col4 = st.columns(4)
                
                stats_data = [
                    (df['User'].nunique(), "Total Users", "var(--primary)"),
                    (df[df['Active'] == True]['User'].nunique(), "Active Users", "var(--success)"),
                    (f"{df['TotalHours'].sum():.0f}", "Total Hours", "var(--accent)"),
                    (f"{df['TotalHours'].mean():.1f}" if len(df) > 0 else "0.0", "Avg Hours", "var(--warning)")
                ]
                
                for i, (value, label, color) in enumerate(stats_data):
                    with [col1, col2, col3, col4][i]:
                        st.markdown(f"""
                            <div style='text-align: center; padding: 1rem; background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)); border-radius: 16px; border: 1px solid var(--glass-border);'>
                                <div style='font-size: 1.5rem; font-weight: 800; color: {color}; margin-bottom: 0.5rem;'>{value}</div>
                                <div style='font-size: 0.75rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px;'>{label}</div>
                            </div>
                        """, unsafe_allow_html=True)
                
                # Advanced Charts
                st.markdown("#### Detailed Analysis")
                
                chart_tab1, chart_tab2, chart_tab3 = st.tabs(["Performance Trends", "User Distribution", "Time Analysis"])
                
                with chart_tab1:
                    if 'Date' in df.columns:
                        # Weekly trend
                        df_weekly = df.copy()
                        df_weekly['Week'] = df_weekly['Date'].dt.isocalendar().week
                        weekly_stats = df_weekly.groupby('Week').agg({
                            'TotalHours': 'sum',
                            'User': 'nunique'
                        }).reset_index()
                        
                        fig = make_subplots(specs=[[{"secondary_y": True}]])
                        
                        fig.add_trace(
                            go.Bar(
                                x=weekly_stats['Week'],
                                y=weekly_stats['TotalHours'],
                                name='Total Hours',
                                marker_color='#4361ee'
                            ),
                            secondary_y=False
                        )
                        
                        fig.add_trace(
                            go.Scatter(
                                x=weekly_stats['Week'],
                                y=weekly_stats['User'],
                                name='Active Users',
                                mode='lines+markers',
                                line=dict(color='#4cc9f0', width=3)
                            ),
                            secondary_y=True
                        )
                        
                        fig.update_layout(
                            title='Weekly Performance Trends',
                            plot_bgcolor='rgba(0,0,0,0)',
                            paper_bgcolor='rgba(0,0,0,0)',
                            font_color='#ffffff',
                            height=400
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                
                with chart_tab2:
                    # User activity distribution
                    user_activity = df.groupby('User').agg({
                        'TotalHours': 'sum',
                        'Active': 'last',
                        'Date': 'nunique'
                    }).reset_index()
                    
                    fig = px.scatter(
                        user_activity,
                        x='Date',
                        y='TotalHours',
                        size='TotalHours',
                        color='Active',
                        title='User Activity Distribution',
                        hover_name='User',
                        size_max=50,
                        color_discrete_map={True: '#4ade80', False: '#f87171'}
                    )
                    fig.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff',
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with chart_tab3:
                    # Time analysis
                    if 'CheckIn' in df.columns and 'CheckOut' in df.columns:
                        # Calculate average check-in/out times
                        df_time = df.copy()
                        df_time['CheckInHour'] = pd.to_datetime(df_time['CheckIn'], errors='coerce').dt.hour
                        df_time['CheckOutHour'] = pd.to_datetime(df_time['CheckOut'], errors='coerce').dt.hour
                        
                        avg_checkin = df_time['CheckInHour'].mean()
                        avg_checkout = df_time['CheckOutHour'].mean()
                        
                        st.markdown(f"""
                            <div style='display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 2rem;'>
                                <div style='padding: 1.5rem; background: linear-gradient(135deg, rgba(67, 97, 238, 0.15), rgba(67, 97, 238, 0.05)); border-radius: 16px; border: 1px solid rgba(67, 97, 238, 0.3);'>
                                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem;'>Avg Check-in</div>
                                    <div style='font-size: 2rem; font-weight: 800; color: var(--primary);'>{avg_checkin:.1f}:00</div>
                                </div>
                                <div style='padding: 1.5rem; background: linear-gradient(135deg, rgba(76, 201, 240, 0.15), rgba(76, 201, 240, 0.05)); border-radius: 16px; border: 1px solid rgba(76, 201, 240, 0.3);'>
                                    <div style='font-size: 0.875rem; color: var(--gray); font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.5rem;'>Avg Check-out</div>
                                    <div style='font-size: 2rem; font-weight: 800; color: var(--accent);'>{avg_checkout:.1f}:00</div>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        with tab4:
            st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
            st.markdown("<h3 class='card-title'>System Settings</h3>", unsafe_allow_html=True)
            
            st.markdown("#### Configuration")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("##### System Information")
                st.info(f"""
                    **Data Source:** Google Sheets  
                    **Timezone:** Cairo, Egypt (GMT+2)  
                    **Total Records:** {len(df)}  
                    **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                """)
            
            with col2:
                st.markdown("##### Actions")
                
                if st.button("Refresh Data", use_container_width=True):
                    df = load_data()
                    st.success("Data refreshed successfully!")
                    st.rerun()
                
                if st.button("Clear Cache", use_container_width=True, type="secondary"):
                    st.cache_data.clear()
                    st.success("Cache cleared!")
            
            st.markdown("#### Danger Zone")
            st.warning("These actions cannot be undone. Proceed with caution.")
            
            if st.button("Reset All Data", use_container_width=True, type="primary"):
                if st.checkbox("I understand this will delete all data"):
                    global df
                    df = pd.DataFrame(columns=EXPECTED_COLUMNS)
                    save_data()
                    st.success("All data has been reset!")
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
    
    else:
        if admin_password:
            st.error("Invalid password. Access denied.")

# Notification system
if st.session_state.last_action:
    st.toast(f"✓ {st.session_state.last_action}", icon="✅")
    st.session_state.last_action = None

# Auto-refresh data every 60 seconds
if (datetime.now() - st.session_state.get('last_refresh', datetime.now())).seconds > 60:
    df = load_data()
    st.session_state.last_refresh = datetime.now()
