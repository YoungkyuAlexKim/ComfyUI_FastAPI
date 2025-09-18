// Centralized front-end config for gallery and UI tuning
window.APP_CONFIG = {
    gallery: {
        pageSize: 32,           // thumbnails per page
        skeletonCount: 12,      // skeleton tiles while loading
        thumbGridCols: {        // preferred columns by breakpoint (may be overridden by CSS)
            default: 4,
            max1200: 3,
            max480: 2
        }
    }
};

