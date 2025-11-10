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
import json
import os

# Egypt timezone
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# Google Sheets setup for Streamlit Cloud
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Function to get credentials from Streamlit secrets
def get_credentials():
    if 'gcp_service_account' in st.secrets:
        # For Streamlit Cloud
        creds_dict = dict(st.secrets['gcp_service_account'])
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # For local development (fallback)
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
            return True  # Default to True if unclear
    return True

# Load data from Google Sheets with error handling
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_data():
    if SHEET is None:
        # Initialize with string dtype for time columns
        dtypes = {col: "string" for col in TIME_COLUMNS}
        dtypes.update({'User': 'string', 'Date': 'string', 'TotalHours': 'float64',
                       'BreakDuration': 'float64', 'Active': 'boolean'})
        return pd.DataFrame(columns=EXPECTED_COLUMNS).astype(dtypes)
    
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
        # Replace empty strings with pd.NA
        df.replace('', pd.NA, inplace=True)
        # Convert time columns to string
        for col in TIME_COLUMNS:
            df[col] = df[col].astype("string").fillna(pd.NA)
        # Ensure other dtypes
        df['TotalHours'] = pd.to_numeric(df['TotalHours'], errors='coerce').fillna(0.0).astype("float64")
        df['BreakDuration'] = pd.to_numeric(df['BreakDuration'], errors='coerce').fillna(0.0).astype("float64")
        # Convert Active safely
        df['Active'] = df['Active'].apply(to_boolean).astype("boolean")
        # Convert Date to datetime for charting
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        return df
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {str(e)}")
        # Initialize with string dtype for time columns
        dtypes = {col: "string" for col in TIME_COLUMNS}
        dtypes.update({'User': 'string', 'Date': 'string', 'TotalHours': 'float64',
                       'BreakDuration': 'float64', 'Active': 'boolean'})
        return pd.DataFrame(columns=EXPECTED_COLUMNS).astype(dtypes)

# Initialize df
df = load_data()

# Function to save data to Google Sheets
def save_data():
    global df
    if SHEET is None:
        st.error("Google Sheets connection not available")
        return False
    
    try:
        # Temporarily convert Date back to string for saving
        df_save = df.copy()
        df_save['Date'] = df_save['Date'].dt.strftime('%Y-%m-%d')
        # Clear the sheet
        SHEET.clear()
        # Add header
        SHEET.append_row(EXPECTED_COLUMNS)
        # Prepare data as list of lists, replacing pd.NA with empty string for Sheets
        data = df_save.replace({pd.NA: ''}).values.tolist()
        # Append rows
        if data:
            SHEET.append_rows(data)
        return True
    except Exception as e:
        st.error(f"Error saving data to Google Sheets: {str(e)}")
        return False

# Function to restore data from Excel
def restore_from_excel(uploaded_file):
    global df
    try:
        uploaded_df = pd.read_excel(uploaded_file, sheet_name='DataMatrix')
        # Validate columns
        if not all(col in uploaded_df.columns for col in ['User', 'Date']):
            st.error("Uploaded Excel file must contain 'User' and 'Date' columns.")
            return False
        # Ensure all expected columns are present
        for col in EXPECTED_COLUMNS:
            if col not in uploaded_df.columns:
                if col == 'Active':
                    uploaded_df[col] = True
                elif col in TIME_COLUMNS:
                    uploaded_df[col] = pd.NA
                else:
                    uploaded_df[col] = pd.NA
        # Convert time columns to string
        for col in TIME_COLUMNS:
            uploaded_df[col] = uploaded_df[col].astype("string").fillna(pd.NA)
        # Ensure other columns have correct dtypes
        uploaded_df['User'] = uploaded_df['User'].astype("string")
        uploaded_df['Date'] = pd.to_datetime(uploaded_df['Date'], errors='coerce')
        uploaded_df['TotalHours'] = uploaded_df['TotalHours'].astype("float64")
        uploaded_df['BreakDuration'] = uploaded_df['BreakDuration'].astype("float64")
        # Convert Active safely
        uploaded_df['Active'] = uploaded_df['Active'].apply(to_boolean).astype("boolean")
        # Merge with existing data, prioritizing uploaded data for duplicates
        df = pd.concat([df, uploaded_df]).drop_duplicates(subset=['User', 'Date', 'CheckIn'], keep='last').reset_index(drop=True)
        return save_data()
    except Exception as e:
        st.error(f"Error restoring data: {str(e)}")
        return False

# Function to calculate shift date (shift starts at 4 PM, ends at 12 AM next day, but date is the start day)
def get_shift_date():
    now = datetime.now(EGYPT_TZ)
    if now.hour < 4 or (now.hour == 4 and now.minute == 0):
        return (now - timedelta(days=1)).date()
    else:
        return now.date()

# Function to format time as 12-hour string (e.g., "12:45 AM")
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

# Ultra-enhanced Custom CSS for an even more impressive, beautiful, and professional GUI
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Roboto:wght@300;400;700&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap');
    :root {
        --primary-color: #00ffea;
        --secondary-color: #ff00ff;
        --accent-color: #ffd700;
        --bg-gradient-start: #0a0922;
        --bg-gradient-mid: #1e1b4e;
        --bg-gradient-end: #13132b;
        --text-color: #f0f0f0;
        --card-bg: rgba(255, 255, 255, 0.08);
        --border-color: rgba(255, 255, 255, 0.15);
        --shadow-color: rgba(0, 255, 234, 0.4);
        --glow-shadow: 0 0 12px var(--primary-color), 0 0 24px var(--secondary-color), 0 0 36px var(--accent-color);
    }
    body, .stApp {
        background: linear-gradient(135deg, var(--bg-gradient-start), var(--bg-gradient-mid), var(--bg-gradient-end));
        background-size: 600% 600%;
        animation: gradientShift 25s ease infinite;
        color: var(--text-color);
        font-family: 'Montserrat', sans-serif;
        overflow: hidden;
    }
    @keyframes gradientShift {
        0% { background-position: 0% 0%; }
        50% { background-position: 100% 100%; }
        100% { background-position: 0% 0%; }
    }
    .css-1lcbmhc {
        background: var(--card-bg);
        backdrop-filter: blur(20px);
        border-right: 1px solid var(--border-color);
        border-radius: 20px;
        margin: 20px;
        box-shadow: 0 6px 40px rgba(0, 0, 0, 0.15);
        padding: 15px;
    }
    .nav-link {
        color: var(--accent-color) !important;
        font-size: 22px;
        padding: 18px;
        border-radius: 12px;
        transition: all 0.5s cubic-bezier(0.68, -0.55, 0.27, 1.55);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .nav-link:hover {
        background: rgba(255, 215, 0, 0.15) !important;
        transform: translateX(10px) scale(1.1);
        box-shadow: var(--glow-shadow);
        color: var(--text-color) !important;
    }
    .nav-link-selected {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color), var(--accent-color)) !important;
        color: var(--text-color) !important;
        box-shadow: 0 0 20px var(--accent-color);
        transform: scale(1.1);
    }
    h1, h2, h3 {
        color: var(--accent-color);
        font-family: 'Orbitron', sans-serif;
        font-weight: 700;
        text-shadow: var(--glow-shadow);
        animation: neonPulse 2s ease-in-out infinite alternate;
        letter-spacing: 2px;
    }
    @keyframes neonPulse {
        from { text-shadow: 0 0 6px var(--primary-color), 0 0 12px var(--secondary-color), 0 0 18px var(--accent-color); }
        to { text-shadow: 0 0 18px var(--primary-color), 0 0 36px var(--secondary-color), 0 0 54px var(--accent-color); }
    }
    .card {
        background: var(--card-bg);
        backdrop-filter: blur(20px);
        border: 1px solid var(--border-color);
        border-radius: 25px;
        padding: 30px;
        margin: 25px 0;
        box-shadow: 0 10px 40px var(--shadow-color);
        transition: all 0.5s ease;
        animation: fadeInScale 1s ease-out;
        position: relative;
        overflow: hidden;
        border-image: linear-gradient(var(--primary-color), var(--secondary-color)) 1;
    }
    .card::before {
        content: '';
        position: absolute;
        top: -100%;
        left: 0;
        width: 100%;
        height: 100%;
        background: linear-gradient(transparent, rgba(255,255,255,0.2), transparent);
        transition: top 0.5s ease;
    }
    .card:hover::before {
        top: 100%;
    }
    .card:hover {
        transform: translateY(-10px) scale(1.03);
        box-shadow: 0 15px 60px rgba(255, 215, 0, 0.5);
    }
    @keyframes fadeInScale {
        from { transform: scale(0.95); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
    }
    .stButton > button {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color), var(--accent-color));
        color: var(--text-color);
        border: none;
        padding: 18px 36px;
        font-size: 20px;
        font-weight: 700;
        border-radius: 20px;
        box-shadow: var(--glow-shadow);
        transition: all 0.5s ease;
        position: relative;
        overflow: hidden;
        z-index: 1;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stButton > button::before {
        content: '';
        position: absolute;
        top: 0;
        left: -200%;
        width: 300%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
        transition: left 0.6s ease;
        z-index: -1;
    }
    .stButton > button:hover::before {
        left: 100%;
    }
    .stButton > button:hover {
        transform: scale(1.1) rotate(3deg);
        box-shadow: 0 0 25px var(--accent-color);
    }
    .stTextInput > div > div > input, .stSelectbox > div > select {
        background: var(--card-bg);
        color: var(--text-color);
        border: 1px solid var(--accent-color);
        border-radius: 20px;
        padding: 18px;
        font-size: 20px;
        box-shadow: 0 0 10px var(--shadow-color);
        transition: all 0.5s ease;
    }
    .stTextInput > div > div > input:focus, .stSelectbox > div > select:focus {
        border-color: var(--secondary-color);
        box-shadow: 0 0 20px var(--secondary-color);
        transform: scale(1.03);
    }
    .dataframe {
        background: var(--card-bg);
        color: var(--text-color);
        border-radius: 20px;
        border: 1px solid var(--shadow-color);
        overflow: hidden;
        box-shadow: var(--glow-shadow);
    }
    .stMarkdown, .stButton, .stTextInput, .stSelectbox {
        animation: fadeInScale 1.2s ease-out;
    }
    .stAlert {
        background: var(--card-bg);
        border: 1px solid var(--accent-color);
        border-radius: 20px;
        color: var(--text-color);
        box-shadow: 0 0 20px var(--shadow-color);
        animation: pulseGlow 2s infinite;
    }
    @keyframes pulseGlow {
        0% { transform: scale(1); box-shadow: 0 0 10px var(--accent-color); }
        50% { transform: scale(1.03); box-shadow: 0 0 30px var(--accent-color); }
        100% { transform: scale(1); box-shadow: 0 0 10px var(--accent-color); }
    }
    .stFormSubmitButton > button {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color), var(--accent-color));
        color: var(--text-color);
        border: none;
        padding: 15px 30px;
        font-size: 20px;
        font-weight: 700;
        border-radius: 20px;
        box-shadow: var(--glow-shadow);
        margin-top: 20px;
        transition: all 0.5s ease;
        text-transform: uppercase;
    }
    .stFormSubmitButton > button:hover {
        transform: scale(1.1);
        box-shadow: 0 0 30px var(--accent-color);
    }
    /* Enhanced particle background */
    body::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: radial-gradient(circle, rgba(0,255,234,0.15) 0%, transparent 50%);
        opacity: 0.1;
        animation: particleFloat 40s linear infinite;
        pointer-events: none;
        z-index: -1;
    }
    @keyframes particleFloat {
        0% { transform: translate(0, 0) rotate(0deg); }
        100% { transform: translate(-200px, -200px) rotate(360deg); }
    }
    /* Add reflection effect to cards */
    .card {
        -webkit-box-reflect: below 2px linear-gradient(transparent, transparent, rgba(0,0,0,0.4));
    }
    /* Chart styling */
    .plotly-chart {
        border-radius: 20px;
        overflow: hidden;
        box-shadow: var(--glow-shadow);
        animation: fadeInScale 1s ease-out;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state for user selection
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None

# Sidebar for navigation
with st.sidebar:
    selected = option_menu(
        menu_title="Control Hub",
        options=["User Portal", "Admin Dashboard"],
        icons=["bi-person-circle", "bi-gear-fill"],
        menu_icon="bi-lightning-charge-fill",
        default_index=0,
        styles={
            "container": {"padding": "15px", "background": "transparent", "border-radius": "20px", "box-shadow": "var(--glow-shadow)"},
            "icon": {"color": "var(--accent-color)", "font-size": "30px"},
            "nav-link": {"font-size": "22px", "margin": "10px", "padding": "18px", "--hover-color": "rgba(255, 215, 0, 0.2)"},
            "nav-link-selected": {"background": "linear-gradient(135deg, var(--primary-color), var(--secondary-color), var(--accent-color))"},
        }
    )

if selected == "User Portal":
    st.title("Hunter Attendance")
    with st.container():
        st.markdown('<div class="card">', unsafe_allow_html=True)
        # Get list of active users
        active_users = sorted(df[df['Active'] == True]['User'].unique().tolist())
        
        with st.form(key="user_selection_form"):
            if not active_users:
                st.warning("No active users available. Please contact the admin to add users.")
                user_name = None
            else:
                user_name = st.selectbox("Select your identity", options=active_users, placeholder="Choose User...", key="user_select")
                submitted = st.form_submit_button("Enter") # Visible button labeled "Enter"
                if submitted:
                    if user_name:
                        st.session_state.selected_user = user_name
                    else:
                        st.error("Please select a user before submitting.")
        st.markdown('</div>', unsafe_allow_html=True)
    # Use session state to display user session
    if st.session_state.selected_user:
        user_name = st.session_state.selected_user
        # Check if user is active
        user_records = df[df['User'] == user_name]
        user_active = user_records['Active'].any() if not user_records.empty else True
        if not user_active:
            st.error("Access Denied: User account has been deleted.")
            st.session_state.selected_user = None # Reset selection
        else:
            shift_date = get_shift_date()
            user_rows = df[(df['User'] == user_name) & (df['Date'] == str(shift_date))]
            # Create a new record for each check-in
            if st.button("Start New Session", key="start_session"):
                new_row = {
                    'User': user_name,
                    'Date': str(shift_date),
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
                    'User': 'string',
                    'Date': 'string',
                    'CheckIn': 'string',
                    'CheckOut': 'string',
                    'Break1Start': 'string',
                    'Break1End': 'string',
                    'Break2Start': 'string',
                    'Break2End': 'string',
                    'Break3Start': 'string',
                    'Break3End': 'string',
                    'TotalHours': 'float64',
                    'BreakDuration': 'float64',
                    'Active': 'boolean'
                })
                df = pd.concat([df, new_row_df], ignore_index=True)
                save_data()
                st.success("New Session Initialized")
                user_rows = df[(df['User'] == user_name) & (df['Date'] == str(shift_date))]
            if not user_rows.empty:
                row_index = user_rows.index[-1] # Most recent record
                st.markdown('<div class="card">', unsafe_allow_html=True)
                col1, col2 = st.columns(2, gap="medium")
                with col1:
                    if st.button("Check In", key=f"check_in_{row_index}") and pd.isna(df.at[row_index, 'CheckIn']):
                        df.at[row_index, 'CheckIn'] = format_time(datetime.now(EGYPT_TZ))
                        total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                        df.at[row_index, 'TotalHours'] = total_hours
                        df.at[row_index, 'BreakDuration'] = break_duration
                        save_data()
                        st.success("Initiated Shift Sequence")
                    for i in range(1, 4):
                        if st.button(f"Break {i} Start", key=f"break_{i}_start_{row_index}") and pd.isna(df.at[row_index, f'Break{i}Start']) and pd.notna(df.at[row_index, 'CheckIn']):
                            if i == 1 or (pd.notna(df.at[row_index, f'Break{i-1}End'])):
                                df.at[row_index, f'Break{i}Start'] = format_time(datetime.now(EGYPT_TZ))
                                total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                                df.at[row_index, 'TotalHours'] = total_hours
                                df.at[row_index, 'BreakDuration'] = break_duration
                                save_data()
                                st.success(f"Break {i} Sequence Started")
                with col2:
                    for i in range(1, 4):
                        if st.button(f"Break {i} End", key=f"break_{i}_end_{row_index}") and pd.notna(df.at[row_index, f'Break{i}Start']) and pd.isna(df.at[row_index, f'Break{i}End']):
                            df.at[row_index, f'Break{i}End'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.success(f"Break {i} Sequence Ended")
                    if st.button("Check Out", key=f"check_out_{row_index}") and pd.notna(df.at[row_index, 'CheckIn']) and pd.isna(df.at[row_index, 'CheckOut']):
                        if all(pd.notna(df.at[row_index, f'Break{i}End']) for i in range(1, 4) if pd.notna(df.at[row_index, f'Break{i}Start'])):
                            df.at[row_index, 'CheckOut'] = format_time(datetime.now(EGYPT_TZ))
                            total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                            df.at[row_index, 'TotalHours'] = total_hours
                            df.at[row_index, 'BreakDuration'] = break_duration
                            save_data()
                            st.success("Shift Sequence Terminated")
                st.markdown('</div>', unsafe_allow_html=True)
                # Display current session status
                st.markdown('<div class="card"><h3>Current Session Status</h3>', unsafe_allow_html=True)
                status_html = f"""
                <div style="padding:25px; border: 1px solid var(--accent-color); border-radius: 20px; box-shadow: var(--glow-shadow);">
                    <p><strong>Check In:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'CheckIn'] if pd.notna(df.at[row_index, 'CheckIn']) else 'Awaiting'}</span></p>
                    <p><strong>Break 1 Start:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break1Start'] if 'Break1Start' in df.columns and pd.notna(df.at[row_index, 'Break1Start']) else 'Awaiting'}</span></p>
                    <p><strong>Break 1 End:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break1End'] if 'Break1End' in df.columns and pd.notna(df.at[row_index, 'Break1End']) else 'Awaiting'}</span></p>
                    <p><strong>Break 2 Start:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break2Start'] if 'Break2Start' in df.columns and pd.notna(df.at[row_index, 'Break2Start']) else 'Awaiting'}</span></p>
                    <p><strong>Break 2 End:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break2End'] if 'Break2End' in df.columns and pd.notna(df.at[row_index, 'Break2End']) else 'Awaiting'}</span></p>
                    <p><strong>Break 3 Start:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break3Start'] if 'Break3Start' in df.columns and pd.notna(df.at[row_index, 'Break3Start']) else 'Awaiting'}</span></p>
                    <p><strong>Break 3 End:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'Break3End'] if 'Break3End' in df.columns and pd.notna(df.at[row_index, 'Break3End']) else 'Awaiting'}</span></p>
                    <p><strong>Check Out:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'CheckOut'] if pd.notna(df.at[row_index, 'CheckOut']) else 'Awaiting'}</span></p>
                    <p><strong>Total Hours:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'TotalHours']:.2f} hours</span></p>
                    <p><strong>Break Duration:</strong> <span style="color: var(--accent-color);">{df.at[row_index, 'BreakDuration']:.2f} hours</span></p>
                </div>
                """
                components.html(status_html, height=360)
                st.markdown('</div>', unsafe_allow_html=True)
                # Display all sessions for the current shift date
                if len(user_rows) > 0:
                    st.markdown('<div class="card"><h3>All Sessions Today</h3>', unsafe_allow_html=True)
                    display_df = user_rows[['CheckIn', 'CheckOut', 'Break1Start', 'Break1End', 'Break2Start', 'Break2End', 'Break3Start', 'Break3End', 'TotalHours', 'BreakDuration']].copy()
                    display_df.fillna('Awaiting', inplace=True)
                    st.dataframe(display_df, use_container_width=True)
                    st.markdown('</div>', unsafe_allow_html=True)
elif selected == "Admin Dashboard":
    st.title("Command Center")
    with st.container():
        st.markdown('<div class="card">', unsafe_allow_html=True)
        admin_password = st.text_input("Enter admin password", type="password", placeholder="Access Code...")
        st.markdown('</div>', unsafe_allow_html=True)
    
    if admin_password == "admin123": # Simple password, change in production
        # Excel upload for data restoration
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Restore Data from Excel")
        uploaded_file = st.file_uploader("Upload Excel file to restore data", type=["xlsx"])
        if uploaded_file:
            if restore_from_excel(uploaded_file):
                st.success("Data restored successfully from Excel!")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        # Editable Data Matrix
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Edit Data Matrix")
        # Filter options
        filter_user = st.selectbox("Filter by User", options=['All'] + sorted(df['User'].unique().tolist()), key='filter_user')
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
            use_container_width=True
        )
        
        if st.button("Save Data Matrix Changes"):
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
            st.success("Data Matrix updated successfully!")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        # Enhanced Analytics Section
        st.markdown('<div class="card"><h3>Attendance Analytics</h3>', unsafe_allow_html=True)
        # Total Hours per User Bar Chart
        total_hours_df = df.groupby('User')['TotalHours'].sum().reset_index()
        fig_bar = px.bar(total_hours_df, x='User', y='TotalHours', title='Total Hours per User',
                         color='TotalHours', color_continuous_scale='plasma')
        fig_bar.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                              font_color='#f0f0f0', title_font_size=24)
        st.plotly_chart(fig_bar, use_container_width=True, theme=None)
        # Select user for line chart
        analytics_user = st.selectbox("Select User for Hourly Trend", options=sorted(df['User'].unique().tolist()), key='analytics_user')
        if analytics_user:
            user_data = df[df['User'] == analytics_user].sort_values('Date')
            fig_line = px.line(user_data, x='Date', y='TotalHours', title=f'Hourly Trend for {analytics_user}',
                               markers=True, color_discrete_sequence=['#00ffea'])
            fig_line.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                                   font_color='#f0f0f0', title_font_size=24)
            st.plotly_chart(fig_line, use_container_width=True, theme=None)
        # Average Break Duration Pie Chart
        avg_break = df.groupby('User')['BreakDuration'].mean().reset_index()
        fig_pie = px.pie(avg_break, values='BreakDuration', names='User', title='Average Break Duration per User',
                         color_discrete_sequence=px.colors.sequential.Plasma)
        fig_pie.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                              font_color='#f0f0f0', title_font_size=24)
        st.plotly_chart(fig_pie, use_container_width=True, theme=None)
        st.markdown('</div>', unsafe_allow_html=True)
        # Edit User Session
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Edit User Session")
        edit_user = st.selectbox("Select User to Edit Session", options=['None'] + sorted(df['User'].unique().tolist()), key='edit_user')
        if edit_user != 'None':
            user_sessions = df[df['User'] == edit_user]
            if not user_sessions.empty:
                session_dates = sorted(user_sessions['Date'].dt.strftime('%Y-%m-%d').unique().tolist())
                edit_date = st.selectbox("Select Session Date", options=session_dates, key='edit_date')
                session_row = user_sessions[user_sessions['Date'].dt.strftime('%Y-%m-%d') == edit_date].iloc[-1]
                session_index = session_row.name
                with st.form(key=f"edit_session_form_{session_index}"):
                    st.write(f"Editing session for {edit_user} on {edit_date}")
                    check_in = st.text_input("Check In", value=session_row['CheckIn'] if pd.notna(session_row['CheckIn']) else "", placeholder="e.g., 04:00 PM")
                    break1_start = st.text_input("Break 1 Start", value=session_row['Break1Start'] if pd.notna(session_row['Break1Start']) else "", placeholder="e.g., 06:00 PM")
                    break1_end = st.text_input("Break 1 End", value=session_row['Break1End'] if pd.notna(session_row['Break1End']) else "", placeholder="e.g., 06:30 PM")
                    break2_start = st.text_input("Break 2 Start", value=session_row['Break2Start'] if pd.notna(session_row['Break2Start']) else "", placeholder="e.g., 08:00 PM")
                    break2_end = st.text_input("Break 2 End", value=session_row['Break2End'] if pd.notna(session_row['Break2End']) else "", placeholder="e.g., 08:30 PM")
                    break3_start = st.text_input("Break 3 Start", value=session_row['Break3Start'] if pd.notna(session_row['Break3Start']) else "", placeholder="e.g., 10:00 PM")
                    break3_end = st.text_input("Break 3 End", value=session_row['Break3End'] if pd.notna(session_row['Break3End']) else "", placeholder="e.g., 10:30 PM")
                    check_out = st.text_input("Check Out", value=session_row['CheckOut'] if pd.notna(session_row['CheckOut']) else "", placeholder="e.g., 12:00 AM")
                    active = st.checkbox("Active", value=session_row['Active'])
                    if st.form_submit_button("Save Session Changes"):
                        # Validate time format
                        time_fields = [check_in, check_out, break1_start, break1_end, break2_start, break2_end, break3_start, break3_end]
                        valid = True
                        for field in time_fields:
                            if field:
                                try:
                                    datetime.strptime(f"{edit_date} {field}", "%Y-%m-%d %I:%M %p")
                                except ValueError:
                                    st.error(f"Invalid time format for {field}. Use HH:MM AM/PM (e.g., 04:00 PM).")
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
                            st.success(f"Session for {edit_user} on {edit_date} updated successfully!")
                            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        # User management: Add new user
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("User Management")
        new_user = st.text_input("Add new user (optional)", placeholder="New User Identity...")
        if st.button("Add User") and new_user:
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
                    'User': 'string',
                    'Date': 'string',
                    'CheckIn': 'string',
                    'CheckOut': 'string',
                    'Break1Start': 'string',
                    'Break1End': 'string',
                    'Break2Start': 'string',
                    'Break2End': 'string',
                    'Break3Start': 'string',
                    'Break3End': 'string',
                    'TotalHours': 'float64',
                    'BreakDuration': 'float64',
                    'Active': 'boolean'
                })
                df = pd.concat([df, new_row_df], ignore_index=True)
                save_data()
                st.success(f"User {new_user} Authorized")
                st.rerun()
            else:
                st.warning(f"User {new_user} already exists and is active.")
        st.markdown('</div>', unsafe_allow_html=True)
        # User management: Remove user
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Remove User")
        remove_user = st.selectbox("Select User to Remove", options=['None'] + sorted(df['User'].unique().tolist()), key='remove_user')
        action = st.selectbox("Action", options=["Keep User", "Delete User (Keep Data)", "Delete User and Data"], key='user_action')
        
        if st.button("Execute Action") and remove_user != 'None':
            user_records = df[df['User'] == remove_user]
            if user_records.empty:
                st.error(f"User {remove_user} not found.")
            else:
                if action == "Delete User (Keep Data)":
                    df.loc[df['User'] == remove_user, 'Active'] = False
                    save_data()
                    st.success(f"User {remove_user} deleted. Historical data retained.")
                elif action == "Delete User and Data":
                    df = df[df['User'] != remove_user]
                    save_data()
                    st.success(f"User {remove_user} and all associated data deleted.")
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        # Download Excel
        def get_excel_download_link(df):
            df_download = df.copy()
            df_download['Date'] = df_download['Date'].dt.strftime('%Y-%m-%d')
            with pd.ExcelWriter('attendance.xlsx', engine='xlsxwriter') as writer:
                df_download.to_excel(writer, index=False, sheet_name='DataMatrix')
            with open('attendance.xlsx', 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode()
            return f'<a href="data:application/octet-stream;base64,{b64}" download="attendance.xlsx">Download Data Matrix</a>'
        
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(get_excel_download_link(df), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.error("Access Denied")