document.addEventListener('DOMContentLoaded', () => {
    function notify(type, message) {
        const text = (typeof message === 'string' && message) ? message : '';
        if (!text) return;
        try {
            if (window.UIToast && typeof window.UIToast[type] === 'function') {
                window.UIToast[type](text);
                return;
            }
        } catch (_) {}
        try { alert(text); } catch (_) {}
    }

    const translateButtons = document.querySelectorAll('.translate-btn, .translate-btn--icon, .translate-btn--small');
    // Prevent duplicate requests (e.g., double-click or multiple buttons bound to same textarea)
    const inFlightTargets = new Set();

    translateButtons.forEach(button => {
        button.addEventListener('click', async (e) => {
            e.preventDefault();
            const targetId = button.dataset.target;
            const textarea = document.getElementById(targetId);
            const originalText = (textarea && typeof textarea.value === 'string') ? textarea.value.trim() : '';

            if (!originalText) {
                notify('info', '변환할 내용을 입력해주세요.');
                return;
            }
            if (targetId && inFlightTargets.has(targetId)) {
                notify('info', '이미 변환 중입니다. 잠시만 기다려주세요.');
                return;
            }

            const originalButtonHtml = button.innerHTML;
            const isSmall = button.classList.contains('translate-btn--small') || button.classList.contains('translate-btn--icon');
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            button.innerHTML = isSmall
                ? '<div class="loading-spinner-small"></div>'
                : '<div class="loading-spinner-small"></div> 변환 중...';
            try {
                if (textarea) textarea.readOnly = true;
            } catch (_) {}
            try {
                if (targetId) inFlightTargets.add(targetId);
            } catch (_) {}
            // Optional, non-intrusive status ping (only when toast exists; avoid alert spam)
            try {
                if (window.UIToast && typeof window.UIToast.info === 'function') {
                    window.UIToast.info('영문 프롬프트로 변환 중입니다...');
                }
            } catch (_) {}

            try {
                const formData = new FormData();
                formData.append('text', originalText);

                const ac = new AbortController();
                const timer = setTimeout(() => {
                    try { ac.abort(); } catch (_) {}
                }, 25000);
                let response = null;
                try {
                    response = await fetch('/api/v1/translate-prompt', {
                        method: 'POST',
                        body: formData,
                        signal: ac.signal,
                    });
                } finally {
                    clearTimeout(timer);
                }

                if (!response.ok) {
                    let detail = '';
                    try {
                        const errorData = await response.json();
                        if (errorData && errorData.detail) detail = String(errorData.detail);
                    } catch (_) {
                        detail = '';
                    }
                    const s = response.status;
                    if (!detail) {
                        if (s === 400) detail = '요청 내용이 올바르지 않습니다. 문장을 조금 더 자세히 적어주세요.';
                        else if (s === 401 || s === 403) detail = '번역 API 키(권한)가 올바르지 않습니다. 관리자에게 문의해 주세요.';
                        else if (s === 429) detail = '요청이 너무 많거나 사용량 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.';
                        else if (s === 503) detail = '번역 기능이 아직 설정되지 않았습니다. (서버 .env에 API 키 필요)';
                        else detail = `변환 중 오류가 발생했습니다. (HTTP ${s})`;
                    }
                    throw new Error(detail);
                }

                const result = await response.json();
                if (textarea) {
                    textarea.value = result.translated_text || '';
                    try { textarea.dispatchEvent(new Event('input')); } catch (_) {}
                }
                try { notify('success', '영문 프롬프트로 변환했습니다.'); } catch (_) {}

            } catch (error) {
                console.error('Translation error:', error);
                const msg = (error && error.name === 'AbortError')
                    ? '변환 요청이 너무 오래 걸려 취소되었습니다. 잠시 후 다시 시도해 주세요.'
                    : (error && error.message ? error.message : '변환 실패');
                notify('error', msg);
            } finally {
                button.disabled = false;
                button.innerHTML = originalButtonHtml;
                button.removeAttribute('aria-busy');
                try {
                    if (textarea) textarea.readOnly = false;
                } catch (_) {}
                try {
                    if (targetId) inFlightTargets.delete(targetId);
                } catch (_) {}
            }
        });
    });
});