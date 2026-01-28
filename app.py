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
from gspread.exceptions import APIError

# Egypt timezone
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# Initialize global dataframe as None
df = None

# Google Sheets setup - FIXED VERSION
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", 
          "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_gsheet_client():
    """Get Google Sheets client with proper caching"""
    try:
        if 'gcp_service_account' in st.secrets:
            creds_dict = dict(st.secrets['gcp_service_account'])
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            # For local development with service account file
            creds = Credentials.from_service_account_file("attendance-477813-1ab662e24347.json", scopes=SCOPES)
        
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Failed to initialize Google Sheets: {str(e)}")
        return None

# Initialize Google Sheets client
CLIENT = get_gsheet_client()

# Define expected columns
EXPECTED_COLUMNS = ['User', 'Date', 'CheckIn', 'CheckOut',
                    'Break1Start', 'Break1End', 'Break2Start', 'Break2End',
                    'Break3Start', 'Break3End', 'TotalHours', 'BreakDuration', 'Active']

# Time-related columns to enforce string dtype
TIME_COLUMNS = ['CheckIn', 'CheckOut', 'Break1Start', 'Break1End',
                'Break2Start', 'Break2End', 'Break3Start', 'Break3End']

def process_dataframe(temp_df):
    """Process and clean the dataframe"""
    # Ensure all expected columns exist
    for col in EXPECTED_COLUMNS:
        if col not in temp_df.columns:
            if col == 'Active':
                temp_df[col] = True
            elif col in TIME_COLUMNS:
                temp_df[col] = pd.NA
            else:
                temp_df[col] = pd.NA
    
    # Replace empty strings with NaN
    temp_df.replace('', pd.NA, inplace=True)
    
    # Convert time columns to string
    for col in TIME_COLUMNS:
        temp_df[col] = temp_df[col].astype("string").fillna(pd.NA)
    
    # Convert numeric columns
    temp_df['TotalHours'] = pd.to_numeric(temp_df['TotalHours'], errors='coerce').fillna(0.0).astype("float64")
    temp_df['BreakDuration'] = pd.to_numeric(temp_df['BreakDuration'], errors='coerce').fillna(0.0).astype("float64")
    
    # Convert Active column to boolean
    temp_df['Active'] = temp_df['Active'].apply(lambda x: str(x).lower() in ['true', '1', 't', 'y', 'yes', True, 1] if pd.notna(x) else True)
    
    # Convert Date column
    if not temp_df.empty and 'Date' in temp_df.columns:
        temp_df['Date'] = pd.to_datetime(temp_df['Date'], errors='coerce', format='%Y-%m-%d')
    
    return temp_df

@st.cache_data(ttl=60)
def load_sheet_data():
    """Load data from Google Sheets with caching"""
    try:
        if CLIENT is None:
            st.error("Google Sheets client not initialized")
            return pd.DataFrame(columns=EXPECTED_COLUMNS)
        
        # Try to open the spreadsheet
        try:
            spreadsheet = CLIENT.open("AttendanceSheet")
            sheet = spreadsheet.sheet1
        except gspread.exceptions.SpreadsheetNotFound:
            st.error("Spreadsheet 'AttendanceSheet' not found. Creating new sheet...")
            # Create a new spreadsheet
            spreadsheet = CLIENT.create("AttendanceSheet")
            sheet = spreadsheet.sheet1
            # Add headers
            sheet.append_row(EXPECTED_COLUMNS)
            return pd.DataFrame(columns=EXPECTED_COLUMNS)
        
        # Get all records
        data = sheet.get_all_records()
        
        if not data:
            return pd.DataFrame(columns=EXPECTED_COLUMNS)
            
        temp_df = pd.DataFrame(data)
        return process_dataframe(temp_df)
        
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {str(e)}")
        # Return empty dataframe with correct structure
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

def save_to_sheets():
    """Save global df to Google Sheets"""
    global df
    if df is None or df.empty:
        st.error("No data to save")
        return False
    
    try:
        if CLIENT is None:
            st.error("Google Sheets client not initialized")
            return False
        
        spreadsheet = CLIENT.open("AttendanceSheet")
        sheet = spreadsheet.sheet1
        
        # Prepare data for saving
        df_save = df.copy()
        
        # Convert Date to string format
        if 'Date' in df_save.columns:
            df_save['Date'] = df_save['Date'].dt.strftime('%Y-%m-%d')
        
        # Replace NaN with empty string
        df_save = df_save.fillna('')
        
        # Clear and update sheet
        sheet.clear()
        sheet.append_row(EXPECTED_COLUMNS)
        
        # Convert dataframe to list of lists
        data = df_save.values.tolist()
        if data:
            sheet.append_rows(data)
        
        return True
        
    except Exception as e:
        st.error(f"Error saving to Google Sheets: {str(e)}")
        return False

# Load initial data
df = load_sheet_data()

# Function to restore data from Excel - FIXED
def restore_from_excel(uploaded_file):
    global df
    try:
        uploaded_df = pd.read_excel(uploaded_file, sheet_name=0)  # Read first sheet
        
        # Check for required columns
        if 'User' not in uploaded_df.columns or 'Date' not in uploaded_df.columns:
            st.error("Uploaded Excel file must contain 'User' and 'Date' columns.")
            return False
        
        # Add missing columns
        for col in EXPECTED_COLUMNS:
            if col not in uploaded_df.columns:
                if col == 'Active':
                    uploaded_df[col] = True
                elif col in TIME_COLUMNS:
                    uploaded_df[col] = pd.NA
                elif col in ['TotalHours', 'BreakDuration']:
                    uploaded_df[col] = 0.0
                else:
                    uploaded_df[col] = pd.NA
        
        # Process the uploaded dataframe
        uploaded_df = process_dataframe(uploaded_df)
        
        # Merge with existing data
        if df is None or df.empty:
            df = uploaded_df
        else:
            # Create a composite key for deduplication
            df['composite_key'] = df['User'].astype(str) + '_' + df['Date'].astype(str)
            uploaded_df['composite_key'] = uploaded_df['User'].astype(str) + '_' + uploaded_df['Date'].astype(str)
            
            # Remove duplicates from existing df
            df = df[~df['composite_key'].isin(uploaded_df['composite_key'])]
            
            # Append new data
            df = pd.concat([df, uploaded_df], ignore_index=True)
            
            # Drop composite key
            df = df.drop(columns=['composite_key'])
        
        # Save to Google Sheets
        if save_to_sheets():
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

# ULTRA MODERN CSS WITH ADVANCED ANIMATIONS (Same as before, truncated for brevity)
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
    
    /* ... rest of the CSS ... */
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'selected_user' not in st.session_state:
    st.session_state.selected_user = None
if 'last_action' not in st.session_state:
    st.session_state.last_action = None
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'admin_authenticated' not in st.session_state:
    st.session_state.admin_authenticated = False

# Reload button in sidebar
with st.sidebar:
    if st.button("🔄 Reload Data", use_container_width=True):
        st.cache_data.clear()
        global df
        df = load_sheet_data()
        st.session_state.data_loaded = True
        st.rerun()

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
        if df is None or df.empty:
            active_users = []
        else:
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
        
        if df is None or df.empty:
            st.error("No data available")
            st.session_state.selected_user = None
        else:
            user_records = df[df['User'] == user_name]
            user_active = user_records['Active'].any() if not user_records.empty else True
            
            if not user_active:
                st.error("⚠️ ACCESS DENIED: User account has been deactivated.")
                st.session_state.selected_user = None
            else:
                shift_date = get_shift_date()
                user_rows = df[(df['User'] == user_name) & (df['Date'].dt.date == shift_date)]
                
                # Start New Session
                col1, col2, col3 = st.columns([2, 1, 2])
                with col2:
                    if st.button("🎯 INITIATE NEW SESSION", use_container_width=True, key="start_session"):
                        new_row = {
                            'User': user_name,
                            'Date': pd.to_datetime(shift_date),
                            'Active': True,
                            'CheckIn': pd.NA,
                            'CheckOut': pd.NA,
                            'TotalHours': 0.0,
                            'BreakDuration': 0.0
                        }
                        for i in range(1, 4):
                            new_row[f'Break{i}Start'] = pd.NA
                            new_row[f'Break{i}End'] = pd.NA
                        
                        # Add new row to dataframe
                        new_row_df = pd.DataFrame([new_row])
                        global df
                        df = pd.concat([df, new_row_df], ignore_index=True)
                        df = process_dataframe(df)
                        
                        # Save to Google Sheets
                        if save_to_sheets():
                            st.session_state.last_action = "New session initialized"
                            st.success("🚀 SESSION INITIALIZED")
                            st.rerun()
                        else:
                            st.error("Failed to save session")

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
                            if save_to_sheets():
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
                                    if save_to_sheets():
                                        st.session_state.last_action = f"Break {i} started"
                                        st.rerun()
                    
                    with col3:
                        for i in range(1, 4):
                            if st.button(f"🔙 BREAK {i} END", use_container_width=True, key=f"break_{i}_end_{row_index}") and pd.notna(df.at[row_index, f'Break{i}Start']) and pd.isna(df.at[row_index, f'Break{i}End']):
                                df.at[row_index, f'Break{i}End'] = format_time(datetime.now(EGYPT_TZ))
                                total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                                df.at[row_index, 'TotalHours'] = total_hours
                                df.at[row_index, 'BreakDuration'] = break_duration
                                if save_to_sheets():
                                    st.session_state.last_action = f"Break {i} ended"
                                    st.rerun()
                        
                        if st.button("🔴 CHECK OUT", use_container_width=True, key=f"check_out_{row_index}") and pd.notna(df.at[row_index, 'CheckIn']) and pd.isna(df.at[row_index, 'CheckOut']):
                            if all(pd.notna(df.at[row_index, f'Break{i}End']) for i in range(1, 4) if pd.notna(df.at[row_index, f'Break{i}Start'])):
                                df.at[row_index, 'CheckOut'] = format_time(datetime.now(EGYPT_TZ))
                                total_hours, break_duration = calculate_times(df.loc[row_index], shift_date)
                                df.at[row_index, 'TotalHours'] = total_hours
                                df.at[row_index, 'BreakDuration'] = break_duration
                                if save_to_sheets():
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

# Admin Dashboard - FIXED VERSION
elif selected == "⚙️ COMMAND CENTER":
    st.markdown("<h1 class='cyber-header'>QUANTUM COMMAND CENTER</h1>", unsafe_allow_html=True)
    
    # ADMIN ACCESS - FIXED LOGIC
    with st.container():
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        
        if not st.session_state.admin_authenticated:
            admin_password = st.text_input("🔐 ENTER ACCESS CODE", type="password", 
                                          placeholder="Quantum Access Key...", key="admin_pass")
            
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("🔓 UNLOCK", use_container_width=True):
                    if admin_password == "admin123":  # Fixed password check
                        st.session_state.admin_authenticated = True
                        st.session_state.last_action = "Admin access granted"
                        st.rerun()
                    else:
                        st.error("🚫 QUANTUM ACCESS DENIED: Invalid security credentials")
        else:
            st.success("✅ ADMIN ACCESS GRANTED")
            if st.button("🔒 LOCK", use_container_width=True):
                st.session_state.admin_authenticated = False
                st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Only show admin features if authenticated
    if st.session_state.admin_authenticated:
        
        # Data Restoration Section
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📊 DATA RESTORATION MODULE</h3>", unsafe_allow_html=True)
        uploaded_file = st.file_uploader("Upload Excel file to restore data", type=["xlsx"])
        if uploaded_file and st.button("🚀 RESTORE DATA", use_container_width=True):
            if restore_from_excel(uploaded_file):
                st.success("🚀 DATA MATRIX RESTORED SUCCESSFULLY!")
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Matrix Editor
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>🛠️ DATA MATRIX EDITOR</h3>", unsafe_allow_html=True)
        
        if df is None or df.empty:
            st.info("No data available in the system")
        else:
            # Filter options
            col1, col2 = st.columns(2)
            with col1:
                filter_user = st.selectbox("FILTER BY USER", 
                                          options=['All'] + sorted(df['User'].astype(str).unique().tolist()), 
                                          key='filter_user')
            with col2:
                if not df.empty and 'Date' in df.columns:
                    dates = ['All'] + sorted(df['Date'].dt.strftime('%Y-%m-%d').unique().tolist())
                else:
                    dates = ['All']
                filter_date = st.selectbox("FILTER BY DATE", options=dates, key='filter_date')
            
            filtered_df = df.copy()
            if filter_user != 'All':
                filtered_df = filtered_df[filtered_df['User'] == filter_user]
            if filter_date != 'All':
                filtered_df = filtered_df[filtered_df['Date'].dt.strftime('%Y-%m-%d') == filter_date]
            
            # Display and edit data
            if not filtered_df.empty:
                # Create editable dataframe
                edited_df = st.data_editor(
                    filtered_df,
                    column_config={
                        "User": st.column_config.TextColumn("User"),
                        "Date": st.column_config.DateColumn("Date"),
                        "CheckIn": st.column_config.TextColumn("Check In"),
                        "CheckOut": st.column_config.TextColumn("Check Out"),
                        "Break1Start": st.column_config.TextColumn("Break 1 Start"),
                        "Break1End": st.column_config.TextColumn("Break 1 End"),
                        "Break2Start": st.column_config.TextColumn("Break 2 Start"),
                        "Break2End": st.column_config.TextColumn("Break 2 End"),
                        "Break3Start": st.column_config.TextColumn("Break 3 Start"),
                        "Break3End": st.column_config.TextColumn("Break 3 End"),
                        "TotalHours": st.column_config.NumberColumn("Total Hours"),
                        "BreakDuration": st.column_config.NumberColumn("Break Duration"),
                        "Active": st.column_config.CheckboxColumn("Active")
                    },
                    use_container_width=True,
                    height=400,
                    key="data_editor"
                )
                
                if st.button("💾 SAVE CHANGES", use_container_width=True):
                    # Update the main dataframe
                    global df
                    df.update(edited_df)
                    if save_to_sheets():
                        st.success("✅ DATA MATRIX UPDATED SUCCESSFULLY!")
                        st.session_state.last_action = "Data matrix updated"
                        st.rerun()
            else:
                st.info("No data to display with current filters")
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Analytics Section
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📈 QUANTUM ANALYTICS</h3>", unsafe_allow_html=True)
        
        if df is not None and not df.empty:
            # Total Hours per User Bar Chart
            total_hours_df = df.groupby('User')['TotalHours'].sum().reset_index()
            if not total_hours_df.empty:
                fig_bar = px.bar(total_hours_df, x='User', y='TotalHours', 
                               title='TOTAL HOURS PER USER',
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
                analytics_user = st.selectbox("SELECT USER FOR TREND ANALYSIS", 
                                            options=sorted(df['User'].astype(str).unique().tolist()), 
                                            key='analytics_user')
                if analytics_user:
                    user_data = df[df['User'] == analytics_user].sort_values('Date')
                    if not user_data.empty:
                        fig_line = px.line(user_data, x='Date', y='TotalHours', 
                                         title=f'HOURS TREND: {analytics_user}',
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
                if not avg_break.empty and (avg_break['BreakDuration'] > 0).any():
                    fig_pie = px.pie(avg_break, values='BreakDuration', names='User', 
                                   title='AVERAGE BREAK DURATION')
                    fig_pie.update_layout(
                        plot_bgcolor='rgba(0,0,0,0)', 
                        paper_bgcolor='rgba(0,0,0,0)',
                        font_color='#ffffff'
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No data available for analytics")
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # User Management
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>👥 USER MANAGEMENT</h3>", unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["➕ ADD USER", "✏️ EDIT SESSION", "🗑️ REMOVE USER"])
        
        with tab1:
            st.markdown("<h4 style='color: var(--accent-glow);'>ADD NEW USER</h4>", unsafe_allow_html=True)
            new_user = st.text_input("Enter new user name", placeholder="New User Identity...", key="new_user_input")
            if st.button("🔧 ADD USER", use_container_width=True, key="add_user_btn") and new_user:
                if df is None:
                    df = pd.DataFrame(columns=EXPECTED_COLUMNS)
                
                user_records = df[df['User'] == new_user]
                if user_records.empty or not user_records['Active'].any():
                    # Add default session for the user
                    new_row = {
                        'User': new_user,
                        'Date': pd.to_datetime(get_shift_date()),
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
                    global df
                    df = pd.concat([df, new_row_df], ignore_index=True)
                    df = process_dataframe(df)
                    
                    if save_to_sheets():
                        st.success(f"✅ USER {new_user} AUTHORIZED")
                        st.session_state.last_action = f"User {new_user} added"
                        st.rerun()
                else:
                    st.warning(f"⚠️ USER {new_user} ALREADY EXISTS AND IS ACTIVE")
        
        with tab2:
            st.markdown("<h4 style='color: var(--accent-glow);'>EDIT USER SESSION</h4>", unsafe_allow_html=True)
            if df is not None and not df.empty:
                edit_user = st.selectbox("SELECT USER", 
                                       options=['Select User'] + sorted(df['User'].astype(str).unique().tolist()), 
                                       key='edit_user_select')
                
                if edit_user != 'Select User':
                    user_sessions = df[df['User'] == edit_user]
                    if not user_sessions.empty:
                        session_dates = sorted(user_sessions['Date'].dt.strftime('%Y-%m-%d').unique().tolist())
                        edit_date = st.selectbox("SELECT SESSION DATE", 
                                               options=session_dates, 
                                               key='edit_date_select')
                        
                        session_row = user_sessions[user_sessions['Date'].dt.strftime('%Y-%m-%d') == edit_date].iloc[-1]
                        session_index = session_row.name
                        
                        with st.form(key=f"edit_session_form"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                check_in = st.text_input("Check In", 
                                                        value=str(session_row['CheckIn']) if pd.notna(session_row['CheckIn']) else "",
                                                        placeholder="04:00 PM")
                                break1_start = st.text_input("Break 1 Start", 
                                                           value=str(session_row['Break1Start']) if pd.notna(session_row['Break1Start']) else "",
                                                           placeholder="06:00 PM")
                                break1_end = st.text_input("Break 1 End", 
                                                         value=str(session_row['Break1End']) if pd.notna(session_row['Break1End']) else "",
                                                         placeholder="06:30 PM")
                                break2_start = st.text_input("Break 2 Start", 
                                                           value=str(session_row['Break2Start']) if pd.notna(session_row['Break2Start']) else "",
                                                           placeholder="08:00 PM")
                            
                            with col2:
                                break2_end = st.text_input("Break 2 End", 
                                                         value=str(session_row['Break2End']) if pd.notna(session_row['Break2End']) else "",
                                                         placeholder="08:30 PM")
                                break3_start = st.text_input("Break 3 Start", 
                                                           value=str(session_row['Break3Start']) if pd.notna(session_row['Break3Start']) else "",
                                                           placeholder="10:00 PM")
                                break3_end = st.text_input("Break 3 End", 
                                                         value=str(session_row['Break3End']) if pd.notna(session_row['Break3End']) else "",
                                                         placeholder="10:30 PM")
                                check_out = st.text_input("Check Out", 
                                                        value=str(session_row['CheckOut']) if pd.notna(session_row['CheckOut']) else "",
                                                        placeholder="12:00 AM")
                            
                            active = st.checkbox("Active", value=bool(session_row['Active']))
                            
                            if st.form_submit_button("💾 SAVE SESSION", use_container_width=True):
                                # Update the session
                                df.at[session_index, 'CheckIn'] = check_in if check_in else pd.NA
                                df.at[session_index, 'CheckOut'] = check_out if check_out else pd.NA
                                df.at[session_index, 'Break1Start'] = break1_start if break1_start else pd.NA
                                df.at[session_index, 'Break1End'] = break1_end if break1_end else pd.NA
                                df.at[session_index, 'Break2Start'] = break2_start if break2_start else pd.NA
                                df.at[session_index, 'Break2End'] = break2_end if break2_end else pd.NA
                                df.at[session_index, 'Break3Start'] = break3_start if break3_start else pd.NA
                                df.at[session_index, 'Break3End'] = break3_end if break3_end else pd.NA
                                df.at[session_index, 'Active'] = active
                                
                                # Recalculate times
                                total_hours, break_duration = calculate_times(df.loc[session_index], edit_date)
                                df.at[session_index, 'TotalHours'] = total_hours
                                df.at[session_index, 'BreakDuration'] = break_duration
                                
                                if save_to_sheets():
                                    st.success(f"✅ SESSION FOR {edit_user} ON {edit_date} UPDATED!")
                                    st.session_state.last_action = f"Session for {edit_user} updated"
                                    st.rerun()
        
        with tab3:
            st.markdown("<h4 style='color: var(--accent-glow);'>REMOVE USER</h4>", unsafe_allow_html=True)
            if df is not None and not df.empty:
                remove_user = st.selectbox("SELECT USER TO REMOVE", 
                                         options=['Select User'] + sorted(df['User'].astype(str).unique().tolist()), 
                                         key='remove_user_select')
                action = st.selectbox("ACTION", 
                                    options=["Keep User", "Deactivate User (Keep Data)", "Delete User and All Data"], 
                                    key='user_action_select')
                
                if st.button("⚡ EXECUTE ACTION", use_container_width=True, key="execute_action") and remove_user != 'Select User':
                    user_records = df[df['User'] == remove_user]
                    if user_records.empty:
                        st.error(f"❌ USER {remove_user} NOT FOUND")
                    else:
                        if action == "Deactivate User (Keep Data)":
                            df.loc[df['User'] == remove_user, 'Active'] = False
                            if save_to_sheets():
                                st.success(f"✅ USER {remove_user} DEACTIVATED. HISTORICAL DATA RETAINED.")
                        elif action == "Delete User and All Data":
                            df = df[df['User'] != remove_user]
                            if save_to_sheets():
                                st.success(f"✅ USER {remove_user} AND ALL ASSOCIATED DATA DELETED.")
                        
                        st.session_state.last_action = f"User {remove_user} {action.lower()}"
                        st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Data Export
        st.markdown("<div class='cyber-card'>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: var(--primary-glow);'>📤 DATA EXPORT</h3>", unsafe_allow_html=True)
        
        def get_excel_download_link():
            if df is None or df.empty:
                return "No data available for export"
            
            df_download = df.copy()
            df_download['Date'] = df_download['Date'].dt.strftime('%Y-%m-%d')
            df_download = df_download.fillna('')
            
            # Create Excel file
            output = pd.ExcelWriter('attendance_data.xlsx', engine='xlsxwriter')
            df_download.to_excel(output, index=False, sheet_name='AttendanceData')
            output.close()
            
            # Read the file and create download link
            with open('attendance_data.xlsx', 'rb') as f:
                data = f.read()
            b64 = base64.b64encode(data).decode()
            return f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="attendance_data.xlsx" style="display: inline-block; padding: 0.5rem 1rem; background: linear-gradient(135deg, rgba(0, 242, 255, 0.2), rgba(255, 0, 255, 0.2)); border: 1px solid var(--cyber-border); border-radius: 5px; color: var(--text-neon); text-decoration: none; font-family: Exo 2, sans-serif; font-weight: 600;">📥 DOWNLOAD DATA MATRIX</a>'
        
        download_link = get_excel_download_link()
        if "No data available" in download_link:
            st.info(download_link)
        else:
            st.markdown(download_link, unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)

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
        <div style='font-size: 0.8rem; color: var(--stardust); margin-top: 10px;'>
            Data Rows: {len(df) if df is not None else 0}<br>
            Active Users: {len(df[df['Active'] == True]['User'].unique()) if df is not None and not df.empty else 0}
        </div>
    </div>
""", unsafe_allow_html=True)

# Add debug info in sidebar (optional)
with st.sidebar.expander("Debug Info"):
    st.write(f"DataFrame is None: {df is None}")
    if df is not None:
        st.write(f"DataFrame shape: {df.shape}")
        st.write(f"Columns: {list(df.columns)}")
        if not df.empty:
            st.write(f"Latest date: {df['Date'].max()}")
            st.write(f"User count: {len(df['User'].unique())}")
