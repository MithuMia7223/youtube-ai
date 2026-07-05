import os
import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import email
from email.mime.text import MIMEText
import base64

# Directory path for token
TOKEN_PATH = 'token.json'

def get_google_credentials(scopes: list):
    """
    Helper function to load and refresh credentials from token.json.
    """
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError("token.json is missing. Please run /auth to authenticate.")
    
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, scopes)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed credentials
            with open(TOKEN_PATH, 'w') as token_file:
                token_file.write(creds.to_json())
        else:
            raise Exception("Invalid or expired credentials. Please run /auth again.")
            
    return creds

def fetch_webpage(url: str) -> str:
    """
    Fetches the text content of a webpage/URL and returns the visible text.
    
    Args:
        url: The web page URL to fetch.
        
    Returns:
        The extracted visible text from the page.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
            
        # Get text
        text = soup.get_text()
        
        # Break into lines and remove leading/trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return text[:5000] # Cap to first 5000 chars for context length
    except Exception as e:
        return f"Error fetching URL {url}: {e}"

def update_google_sheet(sheet_id: str, range_name: str, values: list[str]) -> str:
    """
    Appends a row of values to a Google Sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet spreadsheet.
        range_name: The sheet range (e.g. 'Sheet1!A1').
        values: A list of cell values for the row (e.g., ['John Doe', 'john@example.com']).
        
    Returns:
        Success or error message.
    """
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    try:
        creds = get_google_credentials(scopes)
        service = build('sheets', 'v4', credentials=creds)
        
        body = {
            'values': [values] # Wrap single row in list of rows
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        return f"Successfully updated sheet! {result.get('updates').get('updatedCells')} cells updated."
    except Exception as e:
        return f"Error updating Google Sheet: {e}. Please ensure you authorized Sheet scope."


def send_gmail_email(to_email: str, subject: str, body: str) -> str:
    """
    Sends an email using the user's Gmail account.
    
    Args:
        to_email: Recipient email address.
        subject: Subject line of the email.
        body: Body text of the email.
        
    Returns:
        Success or error message.
    """
    scopes = ['https://www.googleapis.com/auth/gmail.send']
    try:
        creds = get_google_credentials(scopes)
        service = build('gmail', 'v1', credentials=creds)
        
        message = MIMEText(body)
        message['to'] = to_email
        message['subject'] = subject
        
        # Raw string format for Google API
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent_message = service.users().messages().send(userId="me", body={'raw': raw}).execute()
        
        return f"Email successfully sent! Message ID: {sent_message.get('id')}"
    except Exception as e:
        return f"Error sending Gmail: {e}. Please ensure you authorized Gmail scope."

def create_calendar_event(summary: str, start_time_iso: str, end_time_iso: str, description: str = "") -> str:
    """
    Creates an event on the user's Google Calendar.
    
    Args:
        summary: Title/Summary of the event.
        start_time_iso: Start time in ISO format (e.g. '2026-07-05T10:00:00+06:00').
        end_time_iso: End time in ISO format (e.g. '2026-07-05T11:00:00+06:00').
        description: Optional details/description of the event.
        
    Returns:
        Success or error message.
    """
    scopes = ['https://www.googleapis.com/auth/calendar']
    try:
        creds = get_google_credentials(scopes)
        service = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time_iso,
                'timeZone': 'Asia/Dhaka',
            },
            'end': {
                'dateTime': end_time_iso,
                'timeZone': 'Asia/Dhaka',
            }
        }
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created successfully! Event URL: {created_event.get('htmlLink')}"
    except Exception as e:
        return f"Error creating Calendar event: {e}. Please ensure you authorized Calendar scope."

def save_lead(name: str, email: str, phone: str = "", details: str = "") -> str:
    """
    Saves a prospective client or customer lead to the local database store (leads.json).
    
    Args:
        name: The name of the lead.
        email: The email address of the lead.
        phone: The phone number of the lead.
        details: Additional comments, requirements, or notes about the lead.
        
    Returns:
        Confirmation message.
    """
    import json
    lead_file = 'leads.json'
    
    lead_data = {
        'name': name,
        'email': email,
        'phone': phone,
        'details': details
    }
    
    leads = []
    if os.path.exists(lead_file):
        try:
            with open(lead_file, 'r') as f:
                leads = json.load(f)
        except Exception:
            leads = []
            
    leads.append(lead_data)
    
    try:
        with open(lead_file, 'w') as f:
            json.dump(leads, f, indent=4)
        return f"Lead saved successfully! Saved client: {name} ({email})"
    except Exception as e:
        return f"Error saving lead: {e}"

