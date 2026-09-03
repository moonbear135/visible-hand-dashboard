// Cloudflare Worker — 코스피 크롤러/보조지표 모듈 예약 발동 보조 트리거
// (2026-09-01 신설, visible-hand-dashboard TASK_HISTORY #184/#185 후속)
//
// 배경: GitHub Actions 자체 schedule cron이 2026-08-27부터 며칠 연속 몇 시간씩
// 지연되는 문제가 반복됨 — GitHub이 공식적으로 인정한, 예약 작업량 급증에 따른
// 디스패치 레이어 과부하 현상(아직 해결 시점 미정). 이 Worker는 그 약한 고리
// (cron 발동 자체)만 Cloudflare의 더 안정적인 시계로 보완함 — 실제 크롤링
// 실행은 여전히 GitHub Actions에서 그대로 돔.
//
// 로직은 딱 하나: "오늘(KST) 이미 이 워크플로우가 실행된 적 있나?" 확인 →
// 없으면 workflow_dispatch로 딱 한 번 깨움. 그 이상의 재시도·실패 감지·상태
// 저장은 하지 않음(감시의 감시 금지 원칙) — 그건 기존 워치독
// (watch_schedule_health.yml, 매일 18:00 KST)의 몫으로 그대로 남겨둠.
//
// 저장소 쪽 scrape.yml / indicator_kr.yml 의 schedule: 은 일단 그대로 둠 —
// 이 Worker의 "오늘 이미 실행 기록 있으면 건너뜀" 체크가 중복 실행을 대부분
// 막아주고(GitHub 자체 cron이 제때 돌면 이 Worker는 조용히 아무것도 안 함),
// 혹시 이 Worker 쪽에 문제가 생겨도 GitHub 자체 cron이 여전히 살아있는
// 이중 안전장치가 됨.
//
// ⚠️ 단, 반대 순서 — 이 Worker가 먼저 깨우고 GitHub 자체 cron이 몇 시간 **뒤에**
// 늦게 발동하는 경우 — 는 이 체크로 못 막음(실측: 2026-09-02·09-03 이틀 연속
// 두 워크플로우 모두 하루 두 번 커밋됨). 그 쪽은 2026-09-04부터 수집기 자체의
// `--skip-if-not-ready`(오늘 자 스냅샷이 이미 SUCCESS 면 아무것도 안 하고 exit 0,
// collector_kospi200.py / collector_indicator_kr.py)가 막음. 이 Worker 의 로직은 그대로 —
// dispatch 는 여전히 입력 없이(ref=main 만) 보내므로 force 기본값 false 로 점검이 켜짐.

const REPO_OWNER = "moonbear135";
const REPO_NAME = "visible-hand-dashboard";

// ⚠️ 이 키 값은 Cloudflare 대시보드의 Cron Trigger 설정값과 문자 그대로
// 정확히 같아야 매칭됩니다. Settings > Trigger events 에서 등록한 두 값과
// 다르면 이 Worker는 아무 대상도 못 찾고 조용히 아무 일도 안 합니다.
const CRON_TARGETS = {
  "10 7 * * 1-5": "scrape.yml",        // UTC 07:10 = KST 16:10 (scrape.yml 자체 예정: 16:05)
  "5 8 * * 1-5": "indicator_kr.yml",   // UTC 08:05 = KST 17:05 (indicator_kr.yml 자체 예정: 17:00)
};

export default {
  // 브라우저로 이 Worker 주소를 직접 열었을 때 보여줄 안내문 — 이 Worker는
  // Cron으로만 동작하고 HTTP 요청 자체는 아무 기능도 없습니다.
  async fetch() {
    return new Response(
      "visible-hand-dashboard 예약 발동 보조 트리거 — Cron으로만 동작합니다.",
      { headers: { "content-type": "text/plain; charset=utf-8" } }
    );
  },

  async scheduled(event, env, ctx) {
    const file = CRON_TARGETS[event.cron];
    if (!file) {
      console.error(`알 수 없는 cron 값: "${event.cron}" — CRON_TARGETS에 등록 안 됨`);
      return;
    }
    // waitUntil로 감싸서, Worker가 응답을 돌려준 뒤에도 fetch가 끝날 때까지
    // 실행이 계속 이어지게 함(Cloudflare Workers의 표준 패턴).
    ctx.waitUntil(checkAndDispatch(file, env));
  },
};

async function checkAndDispatch(file, env) {
  const token = env.GH_TOKEN;
  if (!token) {
    console.error("GH_TOKEN 시크릿이 설정 안 됨 — Settings > Variables and Secrets 확인 필요");
    return;
  }

  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "visible-hand-scrape-trigger",
  };

  // 1) 오늘(KST) 이미 실행된 적 있는지 확인 — 성공/실패/진행중 상관없이
  //    "오늘 날짜로 만들어진 실행 기록이 있는가"만 봄(중복 발동 방지가
  //    목적이지, 성공 여부 판정은 기존 워치독의 몫이라 여기선 안 함).
  const runsUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${file}/runs?per_page=5`;
  const runsRes = await fetch(runsUrl, { headers });

  if (!runsRes.ok) {
    console.error(`[${file}] 실행 이력 조회 실패: HTTP ${runsRes.status} ${await runsRes.text()}`);
    return;
  }

  const runsData = await runsRes.json();
  const todayKst = kstDateString(new Date());
  const ranToday = (runsData.workflow_runs || []).some(
    (run) => kstDateString(new Date(run.created_at)) === todayKst
  );

  if (ranToday) {
    console.log(`[${file}] 오늘(${todayKst} KST) 이미 실행 기록 있음 — 건너뜀`);
    return;
  }

  // 2) 없으면 workflow_dispatch로 깨움 (ref=main, 대상 워크플로우 파일과
  //    동일하게 main 브랜치 기준으로 실행).
  const dispatchUrl = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${file}/dispatches`;
  const dispatchRes = await fetch(dispatchUrl, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });

  if (dispatchRes.ok) {
    console.log(`[${file}] 오늘 실행 기록 없어 workflow_dispatch 트리거함 (${todayKst} KST)`);
  } else {
    console.error(`[${file}] dispatch 실패: HTTP ${dispatchRes.status} ${await dispatchRes.text()}`);
  }
}

// UTC epoch → KST(UTC+9, 한국은 서머타임 없음) 기준 YYYY-MM-DD 문자열
function kstDateString(date) {
  const kst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return kst.toISOString().slice(0, 10);
}
