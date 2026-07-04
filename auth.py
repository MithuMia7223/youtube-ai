import os
import sys
import urllib.parse as urlparse
from youtube_helper import get_auth_url, save_token_from_code

def main():
    print("=== YouTube Data API Authorization CLI ===")
    
    if not os.path.exists('client_secrets.json'):
        print("\n[ERROR] client_secrets.json not found in the current directory!")
        print("\nTo fix this:")
        print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
        print("2. Create a project and enable the 'YouTube Data API v3'.")
        print("3. Configure the OAuth Consent Screen (Set status to 'Testing' and add your email as a test user).")
        print("4. Go to Credentials -> Create Credentials -> OAuth Client ID.")
        print("5. Select Application Type: 'Web application'.")
        print("6. Add the following Authorized Redirect URI:")
        print("   http://localhost")
        print("7. Download the credentials JSON, rename it to 'client_secrets.json' and place it in this folder.")
        sys.exit(1)
        
    try:
        auth_url = get_auth_url()
        print("\n1. Please visit the following URL in your web browser:")
        print(f"\n{auth_url}\n")
        print("2. Authorize the application using your YouTube channel's Google Account.")
        print("3. You will be redirected to a blank/failed page at 'http://localhost/?code=...'")
        print("4. Copy the ENTIRE redirected URL from your browser's address bar and paste it below:")
        
        user_input = input("\nPaste the redirected URL here: ").strip()
        
        # Parse code from URL or use the input directly if they managed to copy just the code
        code = user_input
        if "code=" in user_input:
            parsed = urlparse.urlparse(user_input)
            code_list = urlparse.parse_qs(parsed.query).get('code')
            if code_list:
                code = code_list[0]
                
        if not code:
            print("\n[ERROR] Could not extract the authorization code. Please make sure you copy the entire redirected URL.")
            sys.exit(1)
            
        print("\nExchanging code for access tokens...")
        save_token_from_code(code)
        print("\n[SUCCESS] token.json has been created and saved successfully!")
        print("The Telegram bot is now fully authorized to upload videos to your YouTube channel.")
        
    except Exception as e:
        print(f"\n[ERROR] Authorization failed: {e}")

if __name__ == '__main__':
    main()
