import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def main():
    creds = None
    token_path = 'token.pickle'

    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            'C:/Users/harry/Downloads/client_secret_173541914825-9v0oni7uv7tun84v7bpl2okakkmfr1pn.apps.googleusercontent.com.json',
            SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    print("Access token and refresh token saved to token.pickle")

if __name__ == '__main__':
    main()
