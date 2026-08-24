# 안티그래비티 전달용 — 디자인 업데이트 프롬프트

이전에 안티그래비티가 이미 `china-weather-gif-service`를 새 GitHub 저장소 + 새 Vercel
프로젝트로 배포했다는 전제입니다. 이번엔 새로 배포하는 게 아니라 **이미 배포된 그 저장소의
디자인 관련 파일 7개만 교체**하는 작업입니다. 아래 텍스트를 그대로 복사해서 안티그래비티에
전달하세요.

---

```text
이전에 배포해준 china-weather-gif-service를 다시 새로 배포하지 말고, 이미 만든 GitHub 저장소와
Vercel 프로젝트를 그대로 이어서 업데이트해줘. 저장소/프로젝트 이름을 못 찾으면 새로 만들지 말고
나에게 먼저 물어봐줘.

## 이번 작업의 목적

날씨 GIF의 시각 디자인만 재설계했다. 데이터 파이프라인(NOAA GFS 다운로드, QWeather 연동,
Supabase 업로드, GitHub Actions 스케줄)은 전혀 건드리지 않았고, 아래 7개 파일만 교체하면 된다.
그 외 파일(.env*, supabase/, .github/workflows/, package.json 등)은 절대 손대지 마.

## 교체할 파일 (로컬 원본 → 저장소 내 동일 경로에 덮어쓰기)

새 원본 폴더: /Users/junghwangji/Downloads/china-weather-gif-service-redesign

1. weather_pipeline/render.py
   → GIF 렌더링 디자인 전체 재작성 (색상·타이포·레이아웃·도시 라벨 배치 알고리즘)
2. weather_pipeline/config.py
   → 지도 뷰포트 상단 경계 55.0 → 50.0 (도시가 없는 북쪽 여백을 잘라 지도를 키움)
3. src/app/page.tsx
   → 미리보기 이미지의 width/height를 1000×625 → 1000×618로 변경
   (지도 캔버스 크기가 바뀌었으니 이 숫자를 반드시 같이 바꿔야 함. 다르면 화면에서 GIF가
   눌리거나 늘어나 보임)
4. tests/test_gfs.py
   → GFS 다운로드 요청의 toplat 파라미터 기대값 55 → 50 (config.py 변경에 맞춘 테스트 수정)
5. tests/test_render_layout.py
   → 캔버스 크기를 하드코딩 대신 render.py의 CANVAS_WIDTH_PX / CANVAS_HEIGHT_PX 상수 참조로 변경
6. public/sample/china-weather-sample.gif
   → 새 디자인으로 재생성된 데모 GIF (그대로 덮어쓰기)
7. docs/DESIGN.md (새 파일, 없으면 추가)
   → 이번에 정한 디자인 규칙 문서. 앞으로 이 파일을 참고해서 디자인을 다시 임의로 바꾸지 말 것.

## 작업 순서

1. 기존 저장소를 최신 상태로 pull 받을 것.
2. 위 7개 파일을 로컬 원본 폴더의 내용으로 정확히 교체할 것(diff 기준 이 파일들 외에는 변경 없음).
3. `pip install -e .[test]` 후 `pytest -q`로 12개 테스트가 전부 통과하는지 확인할 것. 실패하면
   임의로 테스트를 고치지 말고 나에게 보고할 것.
4. 변경 사항을 커밋하고 기존 브랜치(main)에 push할 것. 커밋 메시지는 "Redesign weather GIF visuals"
   같은 간단한 영어 요약이면 충분함.
5. push 후 Vercel이 자동으로 재배포되는지 확인할 것. 안 되면 수동으로 재배포를 트리거할 것.
6. GitHub Actions의 `Generate China weather GIF` 워크플로를 workflow_dispatch, gfs_run=auto로
   한 번 수동 실행해서, 고정 URL `/weather/china.gif`가 새 디자인으로 실제 재생성되는지 확인할 것.
7. 재생성된 GIF의 실제 크기가 1000×618인지, `/api/weather/latest`가 정상 응답하는지 확인할 것.

## 절대 하지 말 것

- 이번 디자인 변경분과 무관한 파일(비밀값, 워크플로, Supabase 설정, package.json 등)은 건드리지
  말 것.
- render.py나 config.py를 다시 임의로 디자인하거나 "개선"하지 말 것 — 이미 완성된 디자인을
  그대로 옮기는 작업임.
- 실제 운영 데이터(태풍 등)에 샘플/합성 데이터를 넣지 말 것.

## 보고할 내용

- 커밋 해시와 push 결과
- pytest 결과 (12 passed 인지)
- Vercel 재배포 URL과 상태
- 워크플로 재실행 후 `/weather/china.gif`, `/api/weather/latest` 응답 확인 결과
- 문제가 있었다면 무엇이었는지
```

---

## 참고

- 새 디자인이 어떻게, 왜 바뀌었는지는 `docs/DESIGN.md`에 정리되어 있습니다. 안티그래비티가
  참고하도록 함께 전달해도 좋습니다.
- 저장소/Vercel 프로젝트 이름을 안티그래비티가 기억하지 못하면(새 세션이라 이전 대화 맥락이
  없으면), 직접 저장소 URL이나 Vercel 프로젝트 이름을 알려주셔야 합니다.
