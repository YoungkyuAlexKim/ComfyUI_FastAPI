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
})();
