# 안티그래비티 배포 전달문

아래 지시문과 이 프로젝트 폴더 또는 ZIP을 안티그래비티에 함께 전달합니다. 기존 웹서비스 저장소를 수정하지 않고 새 GitHub 저장소와 새 Vercel 프로젝트로 배포하는 것이 기본 원칙입니다.

## 사용자가 먼저 정할 것

- 새 GitHub 저장소 이름: 예) `china-weather-gif-service`
- 새 Vercel 프로젝트 이름: 예) `china-weather-map`
- 기존 Supabase 프로젝트를 재사용할지 여부
- Vercel 요금제: Hobby 또는 Pro
- 원하는 공개 도메인: 기본 `*.vercel.app` 또는 별도 날씨 서브도메인

## 안티그래비티에 전달할 지시문

```text
첨부한 china-weather-gif-service 프로젝트를 실제 운영 환경에 배포해줘.

이 프로젝트는 이미 구현과 로컬 검증이 끝난 상태다. 새로 만들지 말고 아래 로컬 폴더를 배포 원본으로 사용해줘.

- 완성된 프로젝트 폴더: /Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service
- 동일한 프로젝트 ZIP: /Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service.zip
- 전체 설치·운영 설명서: /Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/README.md
- 배포 전달문: /Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/DEPLOY_WITH_ANTIGRAVITY.md
- 실제 NOAA 57프레임 검증 GIF: /Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/public/sample/china-weather-noaa-2026082018.gif

먼저 프로젝트 폴더와 README를 읽고 현재 구현을 파악한 다음 배포해줘. 로컬 경로에 접근할 수 없다면 새로 구현하지 말고 위 ZIP을 요청해줘.

프로젝트를 만든 목적과 사용자 맥락:
- 이 기능은 중국 여행 정보 서비스·네이버 카페를 이용하는 한국인 여행자가 중국과 대만의 앞으로 7일 날씨를 한눈에 확인하도록 만든 것이다.
- 사용자가 전문 기상도를 해석하게 하는 것이 아니라 여행 결정에 가장 중요한 태풍, 비, 도시별 온도를 우선순위대로 즉시 읽게 하는 것이 핵심이다.
- NOAA/NCEP GFS의 강수·기압·바람을 중국 중심 지도 배경으로 사용하고, QWeather의 읽기 쉬운 도시 날씨와 활성 태풍 정보·제공 경로를 결합한다.
- 베이징·상하이·칭다오·대련·시안·청두·충칭·장자제·광저우·선전·홍콩·타이베이 등 한국인이 자주 찾는 중국·대만 22개 도시를 표시한다.
- 3시간 간격, 최대 168시간의 날씨 변화를 animated GIF 하나로 제공해 웹서비스와 네이버 카페에서 별도 조작 없이 계속 재생되게 한다.
- 지도상의 도시 카드는 움직이지 않고, 태풍만 실제 경로를 따라 이동한다. 태풍이 여러 개면 왼쪽 고정 패널과 태풍 눈에 같은 1·2·3 번호와 색을 사용한다.
- 결과물은 토스·Apple 계열처럼 밝고 정돈된 소비자형 UI이며, 현재 완성된 지도 디자인·도시 배치·글자·색상·레이어는 배포 과정에서 다시 설계하거나 임의로 변경하지 않는다.
- 최종 목적은 자동수집이 계속되는 고정 이미지 URL `/weather/china.gif`를 만들어 기존 웹서비스와 네이버 카페가 언제나 최신 GIF를 같은 주소로 불러오게 하는 것이다.

완료 기준:
- GitHub Actions가 하루 4회 NOAA와 QWeather 데이터를 수집하고, 같은 GFS run은 중복 생성하지 않는다.
- 새 GIF는 Supabase Storage에 버전 파일로 저장되고 DB의 최신 메타데이터가 ready 상태로 갱신된다.
- Vercel의 고정 URL은 사용자가 파일 경로를 바꾸지 않아도 항상 최신 ready GIF를 반환한다.
- 활성 태풍이 없으면 태풍 패널을 숨기고, 태풍이 있으면 실제 API 데이터만 자동 표시한다.

중요한 제약:
1. 기존 웹서비스 저장소와 기존 Vercel 프로젝트의 파일은 수정하지 말 것.
2. 이 코드는 새 GitHub 저장소와 새 Vercel 프로젝트로 독립 배포할 것.
3. 기존 Supabase 프로젝트는 재사용해도 되지만, 먼저 public.weather_assets 테이블과 weather-assets bucket 이름 충돌 여부를 확인할 것. 같은 이름의 다른 용도 데이터가 있으면 실행하지 말고 나에게 보고할 것.
4. SUPABASE_SERVICE_ROLE_KEY, QWEATHER_API_KEY, GitHub token 등 비밀값은 저장소나 로그에 넣지 말고 각 서비스의 Secret/Environment Variables에만 저장할 것.
5. 브라우저 환경변수인 NEXT_PUBLIC_*로 비밀값을 만들지 말 것.

배포 작업:
1. 새 GitHub 저장소를 만들고 이 프로젝트의 내용이 저장소 루트가 되도록 push할 것.
2. Supabase SQL Editor에서 supabase/migrations/001_weather_assets.sql을 실행해 weather_assets 테이블, claim_weather_generation RPC, private weather-assets bucket을 만들 것.
3. GitHub Actions Repository secrets에 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, QWEATHER_API_HOST, QWEATHER_API_KEY를 설정할 것.
4. GitHub Actions의 Generate China weather GIF 워크플로를 workflow_dispatch, gfs_run=auto로 한 번 수동 실행할 것.
5. 실행 후 weather_assets에 status=ready, frame_count=57인 행이 생기고 Storage에 버전 GIF와 manifest가 업로드됐는지 확인할 것.
6. 같은 GitHub 저장소를 새 Vercel 프로젝트로 import할 것.
7. Vercel Production 환경변수에 SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, WEATHER_STORAGE_BUCKET=weather-assets, WEATHER_ASSET_KEY=china-7d, CRON_SECRET을 설정할 것.
8. Vercel이 Pro이고 Vercel에서 GitHub 작업을 즉시 시작하게 할 경우에만 GITHUB_ACTIONS_REPOSITORY와 최소 범위 fine-grained GITHUB_ACTIONS_TOKEN을 추가할 것. 그렇지 않으면 이 두 값은 생략하고 GitHub Actions 자체 스케줄을 하루 4회 생성의 기준으로 사용할 것.
9. Vercel Hobby이면 vercel.json의 하루 1회 Cron을 그대로 사용할 것. Pro이면 원할 때만 schedule을 "15 5,11,17,23 * * *"로 변경할 것.
10. Production 배포 후 아래 두 주소를 확인할 것.
   - /api/weather/latest : status=ready와 최신 gfsRun 반환
   - /weather/china.gif : HTTP 200, Content-Type image/gif, 57프레임 GIF 반환
11. 같은 GFS run으로 작업을 다시 실행했을 때 중복 생성하지 않고 skip되는지 확인할 것.
12. 최종적으로 공개 GIF 전체 주소, 최신 상태 API 주소, GitHub Actions 다음 실행 시각, Vercel Cron 상태를 나에게 보고할 것.

QWeather 태풍 API 권한이 없거나 과금 설정이 안 되어 있다면 도시 날씨만 정상 생성하고 태풍 데이터 실패를 숨기지 말고 보고할 것. 임의의 태풍 데이터를 운영 결과에 넣지 말 것.
```

## 배포 후 사용할 주소

Vercel 배포 도메인이 `https://china-weather-map.vercel.app`이라면 고정 이미지는 다음 주소입니다.

```text
https://china-weather-map.vercel.app/weather/china.gif
```

기존 서비스와 코드까지 합치지 않고 같은 브랜드 주소를 쓰려면 새 Vercel 프로젝트에 `weather.example.com` 같은 서브도메인을 연결하는 방법이 가장 안전합니다.
