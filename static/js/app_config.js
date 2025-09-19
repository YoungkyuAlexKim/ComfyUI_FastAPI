// 프론트엔드 전역 설정 (갤러리/연출 등)
(function () {
  window.APP_CONFIG = window.APP_CONFIG || {};

  // 갤러리 기본값 (이미 값이 있으면 보존)
  window.APP_CONFIG.gallery = window.APP_CONFIG.gallery || {
    // 페이지당 썸네일 개수
    pageSize: 32,
    // 갤러리 로딩 시 표시할 스켈레톤(자리표시자) 개수
    skeletonCount: 12,
    thumbGridCols: {
      // 반응형 그리드 컬럼 수 (CSS에서 재정의될 수 있음)
      // 기본(데스크톱)
      default: 4,
      // 너비 1200px 이하
      max1200: 3,
      // 너비 480px 이하
      max480: 2,
    },
  };

  // 로딩 오버레이/블러/타이핑 및 등장 연출 설정
  window.APP_CONFIG.loading = window.APP_CONFIG.loading || {
    // 연출 사용 여부 (true: 사용, false: 미사용)
    enabled: true,
    // 블러 반경(px) — 결과 이미지/플레이스홀더에 적용
    blurPx: 10,
    // 오버레이 페이드인 시간(ms)
    fadeMs: 300,
    // 로딩 문구 교체 간격(ms)
    messageIntervalMs: 2200,
    // 로딩 문구 타이핑 속도(글자당 ms)
    typingSpeedMs: 80,
    // 새 이미지 등장(페이드인 + 블러 해제) 총 시간(ms)
    revealMs: 2000,
    // 오버레이 페이드아웃 시간(ms) — 페이드인은 fadeMs 사용
    overlayFadeOutMs: 2000,
    // 새 이미지 등장 애니메이션 이징(CSS easing 함수)
    revealEasing: 'ease',
    // 오버레이 페이드 이징(CSS easing 함수)
    overlayEasing: 'ease',
  };

  // UI 표시/숨김 설정
  window.APP_CONFIG.ui = window.APP_CONFIG.ui || {
    // 부정 프롬프트 영역 표시 여부 (기본: 숨김)
    showNegativePrompt: false,
  };

  // 생성 진행률(프로그레스) 설정
  window.APP_CONFIG.progress = window.APP_CONFIG.progress || {
    // 제목(아이콘 포함) 표시 여부
    showTitle: false,
    // 바 높이(px)
    height: 4,
    // 퍼센트 표시 방식: 'none' | 'right' | 'bubble'
    percentMode: 'right',
    // 버블 세부
    bubble: {
      // 진행 바 위 상대 위치(px, 음수면 위로)
      offsetY: -14,
      // 말풍선 최소/최대 위치 보정(px)
      clampPadding: 6,
    },
  };

  // 라이트박스(갤러리 상세) 설정
  window.APP_CONFIG.lightbox = window.APP_CONFIG.lightbox || {
    // 우측 메타 패널 너비(px)
    metaWidth: 320,
    // 페이드인 시간(ms)
    fadeMs: 300,
    // 미디어 영역 배경색(예: 'rgba(17,24,39,0.55)' 또는 '#00000088')
    mediaBg: 'rgba(34, 34, 34, 0.55)',
    // 메타 패널 배경색
    metaBg: 'rgba(34, 34, 34, 0.55)'
  };
})();
