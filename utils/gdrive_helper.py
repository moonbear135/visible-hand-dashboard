import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 서비스 계정 키 파일 경로 및 권한 범위 설정
SERVICE_ACCOUNT_FILE = 'service_account.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """구글 드라이브 API 서비스 객체 생성"""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build('drive', 'v3', credentials=creds)

def upload_to_gdrive(local_file_path: str, drive_folder_id: str):
    """
    지정한 로컬 파일을 구글 드라이브 폴더로 백업합니다.
    이미 같은 이름의 파일이 존재하면 새 버전으로 덮어씁니다(업데이트).
    """
    if not os.path.exists(local_file_path):
        print(f"❌ [에러] 파일이 존재하지 않습니다: {local_file_path}")
        return

    service = get_drive_service()
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

if __name__ == "__main__":
    # 테스트용 실행 (구글 드라이브 폴더 ID 적용 완료)
    TARGET_FOLDER_ID = "1wTMFTI2txGvnzYACkbhWbJZuanxseki7"
    
    # market_history.csv 파일 업로드 테스트
    test_file = "market_history.csv"
    if os.path.exists(test_file):
        upload_to_gdrive(test_file, TARGET_FOLDER_ID)
    else:
        print("테스트할 CSV 파일이 로컬에 없습니다.")
