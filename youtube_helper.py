import os
import re
import json
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]

# We use http://localhost as a standard redirect URI for manual copy-paste flow
REDIRECT_URI = 'http://localhost'

def extract_video_id(url: str) -> str:
    """
    Extracts the 11-character YouTube video ID from a URL.
    """
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def get_transcript(video_id: str) -> str:
    """
    Fetches the transcript of a YouTube video using youtube_transcript_api.
    Prioritizes English, Bengali, and Hindi, but falls back to any available transcript.
    """
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to find preferred languages
        try:
            transcript = transcript_list.find_transcript(['en', 'bn', 'hi'])
        except:
            # Fallback to any manual or auto-generated transcript
            transcript = transcript_list.find_transcript([])
            
        data = transcript.fetch()
        text = " ".join([item['text'] for item in data])
        return text
    except Exception as e:
        print(f"Error fetching transcript for {video_id}: {e}")
        return None

# Global flow reference to preserve code verifier state across get_auth_url and save_token_from_code
_global_flow = None

def get_auth_url() -> str:
    """
    Generates the Google OAuth authorization URL.
    """
    global _global_flow
    if not os.path.exists('client_secrets.json'):
        raise FileNotFoundError("client_secrets.json is missing in the project root.")
        
    _global_flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = _global_flow.authorization_url(prompt='consent', access_type='offline')
    return auth_url

def save_token_from_code(code: str):
    """
    Exchanges authorization code for credentials and saves them to token.json.
    """
    global _global_flow
    if not os.path.exists('client_secrets.json'):
        raise FileNotFoundError("client_secrets.json is missing in the project root.")
        
    # If the script was restarted and global flow is lost, create a fallback flow
    if _global_flow is None:
        _global_flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        
    _global_flow.fetch_token(code=code)
    creds = _global_flow.credentials
    
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())
    return creds

def get_youtube_service():
    """
    Builds and returns the authenticated YouTube Data API v3 service.
    Refreshes the credentials if they are expired.
    """
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open('token.json', 'w') as token_file:
                    token_file.write(creds.to_json())
            except Exception as e:
                print(f"Error refreshing Google Credentials: {e}")
                return None
        else:
            return None
            
    return build('youtube', 'v3', credentials=creds)

def get_channel_stats() -> dict:
    """
    Retrieves the authenticated user's YouTube channel statistics.
    """
    youtube = get_youtube_service()
    if not youtube:
        return None
        
    try:
        response = youtube.channels().list(
            part='snippet,statistics',
            mine=True
        ).execute()
        
        if 'items' in response and len(response['items']) > 0:
            channel = response['items'][0]
            return {
                'channel_title': channel['snippet']['title'],
                'subscriber_count': channel['statistics'].get('subscriberCount', '0'),
                'view_count': channel['statistics'].get('viewCount', '0'),
                'video_count': channel['statistics'].get('videoCount', '0'),
                'custom_url': channel['snippet'].get('customUrl', '')
            }
    except Exception as e:
        print(f"Error fetching channel stats: {e}")
    return None

def upload_video(file_path: str, title: str, description: str, tags: list, privacy_status: str = 'private') -> str:
    """
    Uploads a video to YouTube using the YouTube Data API v3.
    """
    youtube = get_youtube_service()
    if not youtube:
        raise Exception("YouTube service is not authenticated. Run the authentication flow first.")
        
    body = {
        'snippet': {
            'title': title[:100], # YouTube limit is 100 chars
            'description': description[:5000], # YouTube limit is 5000 chars
            'tags': tags,
            'categoryId': '22' # Category 22 is 'People & Blogs' as default
        },
        'status': {
            'privacyStatus': privacy_status, # 'private', 'public', or 'unlisted'
            'selfDeclaredMadeForKids': False
        }
    }
    
    # Upload video
    media = MediaFileUpload(
        file_path,
        chunksize=1024*1024,
        resumable=True
    )
    
    try:
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Upload progress: {int(status.progress() * 100)}%")
                
        return response.get('id')
    except Exception as e:
        print(f"Error during video upload: {e}")
        raise e

def upload_thumbnail(video_id: str, file_path: str) -> bool:
    """
    Uploads a custom thumbnail for a YouTube video.
    """
    youtube = get_youtube_service()
    if not youtube:
        raise Exception("YouTube service is not authenticated.")
        
    try:
        request = youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(file_path)
        )
        response = request.execute()
        print(f"Thumbnail uploaded successfully for video {video_id}: {response}")
        return True
    except Exception as e:
        print(f"Error during thumbnail upload: {e}")
        return False

def get_video_details(video_id: str) -> dict:
    """
    Fetches basic video information using yt-dlp.
    """
    ydl_opts = {'quiet': True}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title'),
                'description': info.get('description'),
                'duration': info.get('duration'),
                'view_count': info.get('view_count'),
                'thumbnail': info.get('thumbnail')
            }
    except Exception as e:
        print(f"Error getting video details using yt_dlp: {e}")
        return None
