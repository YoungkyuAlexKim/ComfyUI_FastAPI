document.addEventListener('DOMContentLoaded', () => {
    const translateButtons = document.querySelectorAll('.translate-btn, .translate-btn--icon, .translate-btn--small');

    translateButtons.forEach(button => {
        button.addEventListener('click', async (e) => {
            e.preventDefault();
            const targetId = button.dataset.target;
            const textarea = document.getElementById(targetId);
            const originalText = (textarea && typeof textarea.value === 'string') ? textarea.value.trim() : '';

            if (!originalText) {
                try { alert('번역할 내용을 입력해주세요.'); } catch (_) {}
                return;
            }

            const originalButtonHtml = button.innerHTML;
            const isSmall = button.classList.contains('translate-btn--small') || button.classList.contains('translate-btn--icon');
            button.disabled = true;
            button.innerHTML = isSmall
                ? '<div class="loading-spinner-small"></div>'
                : '<div class="loading-spinner-small"></div> 번역 중...';

            try {
                const formData = new FormData();
                formData.append('text', originalText);

                const response = await fetch('/api/v1/translate-prompt', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    let detail = '번역 중 오류가 발생했습니다.';
                    try { const errorData = await response.json(); if (errorData && errorData.detail) detail = errorData.detail; } catch (_) {}
                    throw new Error(detail);
                }

                const result = await response.json();
                if (textarea) {
                    textarea.value = result.translated_text || '';
                    try { textarea.dispatchEvent(new Event('input')); } catch (_) {}
                }

            } catch (error) {
                console.error('Translation error:', error);
                try { alert(`오류: ${error.message}`); } catch (_) {}
            } finally {
                button.disabled = false;
                button.innerHTML = originalButtonHtml;
            }
        });
    });
});