배포용 버전 안내

이 폴더는 `kiwoom_mock_realtime_top5.py`를 클라우드에 올릴 수 있게 정리한 배포용 구조입니다.

포함 파일
- streamlit_app.py : 배포용 엔트리 파일
- requirements.txt : 필요한 패키지
- .streamlit/config.toml : Streamlit 서버 설정
- .streamlit/secrets.toml.example : 시크릿 입력 예시

배포 순서
1. 이 폴더 전체를 GitHub 저장소에 올립니다.
2. Streamlit을 실행할 수 있는 배포 플랫폼에서 저장소를 연결합니다.
3. 앱 시작 파일은 `streamlit_app.py` 로 지정합니다.
4. secrets 또는 환경변수에 아래 값을 넣습니다.
   - KIWOOM_APPKEY
   - KIWOOM_SECRETKEY
   - DART_API_KEY (선택)

주의
- 키움 모의실시간 시세를 클라우드에서 쓰려면 계정/허용 환경 설정이 필요할 수 있습니다.
- 키움 시세가 동작하지 않으면 앱은 보조 시세로 동작합니다.
- Open DART 키를 넣으면 공시까지 표시됩니다.
