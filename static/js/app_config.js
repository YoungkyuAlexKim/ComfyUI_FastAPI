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

  // 워크플로우 배너 설정
  // - defaultUrl: 배너 기본 이미지 경로 (없으면 CSS 그라디언트 사용)
  // - heightPx: 배너 높이(px)
  // - map: 워크플로우 ID별 배너 경로 매핑
  window.APP_CONFIG.banners = window.APP_CONFIG.banners || {
    defaultUrl: '',
    heightPx: 180,
    // 전역 기본 표시 여부 (워크플로우 매핑에서 개별 오버라이드 가능)
    showTitleByDefault: true,
    showDescriptionByDefault: true,
    // map은 문자열 경로 또는 확장 객체를 허용합니다.
    // 1) 문자열: 배너 이미지 경로만 지정 (전역 기본 표시 여부 사용)
    // 2) 객체: { url: '...', showTitle: true/false, showDescription: true/false }
    map: {
      'BasicWorkFlow_PixelArt': {
        url: '/static/img/banner/img_banner_workflow_pixelart.png',
        // 예: 이미지에 텍스트가 내장된 경우 아래를 false로 설정
        showTitle: false, // 배너 이미지에 텍스트가 포함돼 있다면 false
        showDescription: false // 배너 이미지에 텍스트가 포함돼 있다면 false
      },
      'BasicWorkFlow_MKStyle': {
        url: '/static/img/banner/img_banner_workflow_mkstyle.png',
        showTitle: false,
        showDescription: false
      },
      'ILXL_Pixelator': {
        url: '/static/img/banner/img_banner_workflow_pixelator.png',
        showTitle: false,
        showDescription: false
      },
      'LOSstyle_Qwen': {
        url: '/static/img/banner/img_banner_workflow_LOSStyle_QWEN.png',
        showTitle: false,
        showDescription: false
      },
      'Z_ImageTurbo': {
        url: '/static/img/banner/img_banner_ZImageTurbo.png',
        showTitle: false,
        showDescription: false
      }
    }
  };

  // 브랜드(좌측 상단) 배너 설정
  window.APP_CONFIG.brand = window.APP_CONFIG.brand || {
    // 배너 이미지 경로 (없으면 텍스트 타이틀 표시)
    url: '/static/img/banner/brand_banner.png',
    // 배너 높이(px)
    heightPx: 80,
    // 텍스트 타이틀 기본 표시 여부 (이미지를 쓰면 보통 false 권장)
    showTextByDefault: false,
    // 여백 조정
    paddingPx: 12,
  };

  // 프롬프트 태그 가중치 설정 (Ctrl+위/아래)
  window.APP_CONFIG.weight = window.APP_CONFIG.weight || {
    // 기본 증감 단위
    step: 0.05,
    // Shift와 함께 사용할 배수 (예: 0.25 → 0.025씩, 2 → 0.2씩)
    shiftMultiplier: 2,
    // 허용 범위
    min: 0.1,
    max: 3.0,
    // 소수점 자리수
    precision: 2
  };
})();
