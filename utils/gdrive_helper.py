import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 구글 드라이브 수정 권한 범위 설정
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_gdrive_service():
    creds = None
    
    # 작업 디렉토리 기준 파일 경로 지정
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    token_path = os.path.join(base_dir, 'token.json')
    credentials_path = os.path.join(base_dir, 'credentials.json')

    # 기존 저장된 로그인 토큰이 있는지 확인
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # 토큰이 없거나 유효하지 않다면 새로 로그인
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"'{credentials_path}' 파일을 찾을 수 없습니다. GCP에서 credentials.json을 다운로드하여 배치해주세요.")
            
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # 다음 실행을 위해 토큰(token.json) 자동 저장
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

def upload_to_gdrive(local_file_path: str, drive_folder_id: str):
    """
    지정한 로컬 파일을 구글 드라이브 폴더로 백업합니다.
    이미 같은 이름의 파일이 존재하면 새 버전으로 덮어씁니다(업데이트).
    """
    if not os.path.exists(local_file_path):
        print(f"❌ [에러] 파일이 존재하지 않습니다: {local_file_path}")
        return

    service = get_gdrive_service()
    file_name = os.path.basename(local_file_path)

    # 폴더 내 동일한 이름의 기존 파일 검색
    query = f"'{drive_folder_id}' in parents and name = '{file_name}' and trashed = false"
    response = service.files().list(q=query, fields="files(id, name)").execute()
    files = response.get('files', [])

    media = MediaFileUpload(local_file_path, resumable=True)

    try:
        if files:
            # 기존 파일 덮어쓰기
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
            print(f"🔄 [{file_name}] 구글 드라이브 업데이트 완료!")
        else:
            # 신규 파일 업로드
            file_metadata = {'name': file_name, 'parents': [drive_folder_id]}
            service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            print(f"🚀 [{file_name}] 구글 드라이브 최초 업로드 완료!")
    except Exception as e:
        print(f"❌ [{file_name}] 업로드 실패: {e}")

def upload_file(local_file_path: str, folder_id: str = "1wTMFTI2txGvnzYACkbhWbJZuanxseki7"):
    """
    지정한 로컬 파일을 구글 드라이브 폴더로 백업합니다. (scrape_daily.py 호환 전용)
    """
    return upload_to_gdrive(local_file_path=local_file_path, drive_folder_id=folder_id)

if __name__ == '__main__':
    # 테스트 업로드
    test_file_path = r"C:\Users\crown\.gemini\antigravity\scratch\visible_hand\market_history.csv"
    TARGET_FOLDER_ID = "1wTMFTI2txGvnzYACkbhWbJZuanxseki7"  # Quant_Dashboard_Data 폴더 ID

    upload_file(test_file_path, folder_id=TARGET_FOLDER_ID)