# 기존 서비스에 나중에 붙일 때

이 프로젝트는 독립 배포가 가능하며 기존 프로젝트에 자동으로 파일을 추가하지 않습니다. 직접 합칠 때는 아래 묶음 단위로 옮기면 됩니다.

## Next.js 공개 URL만 붙이기

다음 파일을 기존 App Router 구조에 맞춰 복사합니다.

```text
src/app/weather/china.gif/route.ts
src/app/api/weather/latest/route.ts
src/app/api/cron/weather/route.ts
src/lib/env.ts
src/lib/supabase-admin.ts
src/lib/weather-assets.ts
src/lib/noaa-gfs.ts
src/lib/github-dispatch.ts
```

기존 프로젝트에 `@supabase/supabase-js`가 이미 있으면 추가 패키지는 없습니다. `vercel.json`에 이 프로젝트의 `crons` 항목만 합칩니다. 기존 `vercel.json` 전체를 덮어쓰지 마세요.

## 배치만 별도 저장소로 운영하기

아래 항목만 배치 저장소에 둡니다.

```text
weather_pipeline/
pyproject.toml
.github/workflows/weather-gif.yml
supabase/migrations/001_weather_assets.sql
```

Next.js 서비스와 배치 저장소가 달라도 같은 Supabase 프로젝트, bucket 이름, `WEATHER_ASSET_KEY`를 사용하면 연결됩니다.

## UI 상태 화면도 가져오기

`src/app/page.tsx`와 `src/app/globals.css`는 독립 프로젝트용 예시 UI입니다. 기존 페이지를 덮어쓰지 말고 필요한 상태 카드 부분만 컴포넌트로 옮기세요. 날씨 기능 자체는 이 UI에 의존하지 않습니다.

## 충돌 없이 확인할 항목

1. 기존 프로젝트의 `@/*` 경로 alias
2. 이미 존재하는 Supabase admin client의 이름과 환경변수
3. 기존 `vercel.json`의 cron 배열
4. `/weather/china.gif` 또는 `/api/weather/latest` 경로 중복 여부
5. CSP가 있다면 Supabase 연결은 서버에서만 일어나므로 별도 image-src 허용이 필요 없는지 확인

