아래 작업을 이어서 실제 운영 환경에 배포해줘.

이 프로젝트는 이미 구현과 로컬 검증이 끝난 독립 서비스다. 새로 만들거나 기존 웹서비스에 코드를 합치지 말고 아래 로컬 폴더를 배포 원본으로 사용해줘.

## 이미 만들어진 로컬 결과물

- 완성된 프로젝트 폴더: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service`
- 동일한 프로젝트 ZIP: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service.zip`
- 전체 설치·운영 설명서: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/README.md`
- Supabase migration: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/supabase/migrations/001_weather_assets.sql`
- GitHub Actions workflow: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/.github/workflows/weather-gif.yml`
- 실제 NOAA 57프레임 검증 GIF: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/public/sample/china-weather-noaa-2026082018.gif`
- 태풍 2개 동작 검증 GIF: `/Users/junghwangji/Documents/Codex/2026-08-21/referenced-chatgpt-conversation-this-is-an/outputs/china-weather-gif-service/public/sample/china-weather-two-typhoon.gif`

먼저 위 프로젝트 폴더와 `README.md`를 읽고 현재 구현 상태를 파악해줘. 로컬 경로에 접근할 수 없다면 새로 구현하지 말고 위 ZIP을 나에게 요청해줘.

## 이 프로젝트를 만든 이유

이 기능은 중국 여행 정보 서비스와 네이버 카페를 이용하는 한국인 여행자가 중국·대만의 앞으로 7일 날씨를 한눈에 확인하도록 만든 것이다.

사용자가 전문 기상도를 해석하게 하는 것이 아니라 여행 결정에 가장 중요한 정보를 아래 순서대로 즉시 읽게 하는 것이 핵심이다.

1. 태풍의 위치와 예상 경로
2. 비가 오는 지역과 강도
3. 주요 여행도시의 날씨 아이콘과 온도

NOAA/NCEP GFS의 강수·해면기압·10m 바람을 중국 중심 지도 배경으로 사용하고, QWeather의 읽기 쉬운 도시 날씨와 활성 태풍 정보·제공 경로를 결합한다. 베이징·상하이·칭다오·대련·시안·청두·충칭·장자제·광저우·선전·홍콩·타이베이 등 한국인이 자주 찾는 중국·대만 22개 도시가 포함되어 있다.

3시간 간격, 최대 168시간의 변화를 animated GIF 하나로 제공해 웹서비스와 네이버 카페에서 별도 조작 없이 계속 재생되게 한다. 도시 카드는 움직이지 않고 태풍만 실제 경로를 따라 이동한다. 여러 태풍은 왼쪽 고정 패널과 지도상의 태풍 눈에 동일한 `1·2·3` 번호와 색상으로 연결한다.

현재 디자인은 토스·Apple 계열처럼 밝고 정돈된 소비자형 UI로 완성되어 있다. 배포 과정에서 지도 디자인, 도시 배치, 글자, 색상, 카드 크기, 레이어 순서를 다시 설계하거나 임의로 변경하지 말아줘.

최종 목적은 자동수집이 계속되는 고정 URL `/weather/china.gif`를 만들어 기존 웹서비스와 네이버 카페가 언제나 같은 주소에서 최신 GIF를 불러오게 하는 것이다.

## 현재 완료된 상태

- 독립 Next.js/Vercel 서비스 구현 완료
- NOAA GFS 부분 다운로드와 57프레임 GIF 렌더링 완료
- QWeather 도시·활성 태풍 연동 코드 완료
- Supabase Storage 업로드와 `weather_assets` 메타데이터 저장 코드 완료
- `/weather/china.gif`, `/api/weather/latest`, `/api/cron/weather` 구현 완료
- 동일 GFS run 중복 생성 방지 구현 완료
- GitHub Actions 자동 배치 구현 완료
- 로컬 테스트 12개와 Next.js production build 통과
- 실제 계정의 비밀값과 배포만 아직 연결되지 않은 상태

## 절대 지켜야 할 범위

1. 기존 웹서비스 저장소와 기존 Vercel 프로젝트의 파일은 수정하지 말 것.
2. 이 폴더를 새 GitHub 저장소와 새 Vercel 프로젝트로 독립 배포할 것.
3. 기존 Supabase 프로젝트는 재사용해도 되지만 먼저 `public.weather_assets` 테이블과 `weather-assets` bucket 이름 충돌 여부를 확인할 것.
4. 같은 이름이 다른 용도로 이미 사용 중이면 migration을 실행하거나 덮어쓰지 말고 나에게 보고할 것.
5. `SUPABASE_SERVICE_ROLE_KEY`, `QWEATHER_API_KEY`, GitHub token은 저장소·코드·로그에 넣지 말고 서비스의 Secret/Environment Variables에만 저장할 것.
6. 비밀값에 `NEXT_PUBLIC_*` 접두사를 사용하지 말 것.
7. 운영 결과에 샘플·합성 태풍 데이터를 넣지 말 것.

## 실제 배포 작업

1. 프로젝트 폴더를 검사하고 `README.md`, `.env.example`, `vercel.json`, GitHub workflow, Supabase migration을 읽어 현재 구조를 확인할 것.
2. 새 GitHub 저장소 `china-weather-gif-service`를 만들고 이 폴더의 내용이 저장소 루트가 되도록 push할 것. 같은 이름이 이미 있으면 임의로 덮어쓰지 말고 보고할 것.
3. 기존 Supabase 프로젝트의 SQL Editor에서 `supabase/migrations/001_weather_assets.sql`을 실행해 `weather_assets` 테이블, `claim_weather_generation` RPC, private `weather-assets` bucket을 만들 것.
4. GitHub Actions Repository secrets에 아래 값을 등록할 것.
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `QWEATHER_API_HOST`
   - `QWEATHER_API_KEY`
5. GitHub Actions의 `Generate China weather GIF` 워크플로를 `workflow_dispatch`, `gfs_run=auto`로 한 번 수동 실행할 것.
6. 실행 후 다음을 검증할 것.
   - `weather_assets.status=ready`
   - `frame_count=57`
   - `generated_at`, `sha256`, GFS run 기록
   - Storage에 버전 GIF와 manifest 업로드
7. 같은 GitHub 저장소를 새 Vercel 프로젝트 `china-weather-map`으로 import할 것. 같은 이름이 이미 있으면 덮어쓰지 말고 보고할 것.
8. Vercel Production 환경변수에 아래 값을 등록할 것.
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `WEATHER_STORAGE_BUCKET=weather-assets`
   - `WEATHER_ASSET_KEY=china-7d`
   - `CRON_SECRET`
9. Vercel이 Pro이고 Vercel에서 GitHub 작업을 즉시 dispatch해야 할 때만 아래 값을 추가할 것.
   - `GITHUB_ACTIONS_REPOSITORY=owner/repository`
   - 최소 범위의 fine-grained `GITHUB_ACTIONS_TOKEN`
10. Vercel Hobby이면 기본 `vercel.json`의 하루 1회 Cron을 유지하고 실제 하루 4회 생성은 GitHub Actions 스케줄이 담당하게 할 것.
11. Vercel Pro이면 사용자가 원하는 경우에만 schedule을 `15 5,11,17,23 * * *`로 변경할 것.
12. Production 배포 후 아래 주소를 검증할 것.
   - `/api/weather/latest`: `status=ready`, 최신 `gfsRun`, `generatedAt`, `frameCount=57` 반환
   - `/weather/china.gif`: HTTP 200, `Content-Type: image/gif`, 최신 57프레임 GIF 반환
13. 같은 GFS run으로 작업을 다시 실행해 중복 생성 없이 skip되는지 검증할 것.
14. 활성 태풍이 없으면 태풍 패널이 숨겨지고, 활성 태풍이 있으면 QWeather 실제 데이터만 표시되는 구조를 유지할 것.

## QWeather 처리

QWeather 일반 도시 날씨와 Tropical Cyclone API의 권한을 각각 확인해줘. 태풍 API 권한 또는 과금 설정이 없으면 도시 날씨 생성은 계속하되, 태풍 데이터 실패를 숨기지 말고 정확히 보고해줘. 운영 화면을 채우기 위해 가짜 태풍을 만들면 안 된다.

## 최종 보고 형식

작업이 끝나면 아래 내용을 한 번에 알려줘.

- 새 GitHub 저장소 주소
- 새 Vercel 프로젝트와 Production 주소
- 고정 GIF 전체 주소: `https://배포도메인/weather/china.gif`
- 최신 상태 API 주소: `https://배포도메인/api/weather/latest`
- Supabase table·bucket 생성 결과
- 첫 실제 GIF의 GFS run, 생성시각, 프레임 수, 파일 크기
- GitHub Actions 다음 자동 실행 시각
- Vercel Cron 활성 상태
- QWeather 도시 API 및 태풍 API 연결 결과
- 남아 있는 오류 또는 사용자가 직접 처리해야 할 항목

필요한 계정 접근이나 비밀값이 없을 때만 정확히 어떤 값이 부족한지 요청하고, 이미 완성된 기능을 처음부터 다시 만들지는 말아줘.
