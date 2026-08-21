import { getLatestReadyAsset } from "@/lib/weather-assets";
import Image from "next/image";

export const dynamic = "force-dynamic";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(new Date(value));
}

export default async function Home() {
  let asset = null;
  let configurationError = false;
  try {
    asset = await getLatestReadyAsset();
  } catch {
    configurationError = true;
  }

  return (
    <main>
      <section className="hero">
        <div className="eyebrow">CHINA WEATHER</div>
        <h1>중국·대만 날씨,<br />한눈에 보세요</h1>
        <p className="lede">
          태풍은 가장 또렷하게, 비는 파란 농도로, 도시 온도는 큰 숫자로 보여주는
          7일 날씨 애니메이션입니다.
        </p>
        <div className="priority" aria-label="핵심 정보">
          <span><i className="typhoonIcon" aria-hidden="true" />태풍 경로</span>
          <span><i className="rainIcon" aria-hidden="true" />비</span>
          <span><i className="temperatureIcon" aria-hidden="true" />도시 온도</span>
        </div>
        <div className="actions">
          <a className="primary" href="/weather/china.gif">
            최신 날씨 보기
          </a>
          <a className="secondary" href="/api/weather/latest">
            생성 상태 확인
          </a>
        </div>
      </section>

      <section className="previewCard">
        <div className="previewHeader">
          <div>
            <span className="label">WEATHER MAP</span>
            <h2>{asset ? "지금 업데이트된 중국·대만 날씨" : "화면 예시"}</h2>
          </div>
          <span className="liveBadge">{asset ? "LIVE" : "SAMPLE"}</span>
        </div>
        <div className="previewFrame">
          <Image
            src={asset ? "/weather/china.gif" : "/sample/china-weather-sample.gif"}
            alt="태풍, 비, 도시별 온도를 보여주는 중국·대만 7일 날씨 지도"
            width={1000}
            height={625}
            unoptimized
            priority
          />
        </div>
      </section>

      <section className="statusCard">
        <div className="statusHeader">
          <div>
            <span className="label">UPDATE STATUS</span>
            <h2>{asset ? "최신 자산 준비됨" : "첫 생성 대기 중"}</h2>
          </div>
          <span className={`dot ${asset ? "ready" : "waiting"}`} aria-hidden="true" />
        </div>

        {asset ? (
          <dl className="facts">
            <div>
              <dt>예보 기준</dt>
              <dd>{asset.gfs_run} UTC</dd>
            </div>
            <div>
              <dt>생성 시각</dt>
              <dd>{formatDate(asset.generated_at)}</dd>
            </div>
            <div>
              <dt>프레임</dt>
              <dd>{asset.frame_count ?? "—"}</dd>
            </div>
            <div>
              <dt>파일 크기</dt>
              <dd>
                {asset.byte_size ? `${(asset.byte_size / 1024 / 1024).toFixed(1)} MB` : "—"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="empty">
            {configurationError
              ? "환경변수 또는 Supabase 마이그레이션을 설정하면 상태가 표시됩니다."
              : "GitHub Actions에서 첫 배치 작업을 실행하면 이곳에 최신 상태가 표시됩니다."}
          </p>
        )}
      </section>

      <section className="flow" aria-label="데이터 흐름">
        <article>
          <span className="featureNumber">01</span>
          <h3>중국이 바로 보여요</h3>
          <p>중국 윤곽을 토스 블루로 강조하고 주변 국가는 한 단계 흐리게 표시합니다.</p>
        </article>
        <article>
          <span className="featureNumber">02</span>
          <h3>도시 날씨가 쉬워요</h3>
          <p>중국 주요 여행 도시와 대만 3개 도시를 큰 카드와 작은 온도 핀으로 빠르게 읽습니다.</p>
        </article>
        <article>
          <span className="featureNumber">03</span>
          <h3>태풍을 놓치지 않아요</h3>
          <p>활성 태풍이 있을 때만 정보 카드와 경로를 크게 보여주고 없으면 숨깁니다.</p>
        </article>
      </section>

      <footer>
        Weather model: NOAA/NCEP GFS · Weather &amp; Typhoon data: QWeather
      </footer>
    </main>
  );
}
