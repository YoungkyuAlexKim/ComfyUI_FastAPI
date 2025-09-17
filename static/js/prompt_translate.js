document.addEventListener('DOMContentLoaded', () => {
    const translateButtons = document.querySelectorAll('.translate-btn');

    translateButtons.forEach(button => {
        button.addEventListener('click', async (e) => {
            e.preventDefault();
            const targetId = button.dataset.target;
            const textarea = document.getElementById(targetId);
            const originalText = textarea.value.trim();

            if (!originalText) {
                alert('번역할 내용을 입력해주세요.');
                return;
            }

            // 버튼 상태 변경
            const originalButtonHtml = button.innerHTML;
            button.disabled = true;
            button.innerHTML = '<div class="loading-spinner-small"></div> 번역 중...';

            try {
                const formData = new FormData();
                formData.append('text', originalText);

                const response = await fetch('/api/v1/translate-prompt', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || '번역 중 오류가 발생했습니다.');
                }

                const result = await response.json();
                textarea.value = result.translated_text;

                // textarea 높이 자동 조절
                textarea.dispatchEvent(new Event('input'));

            } catch (error) {
                console.error('Translation error:', error);
                alert(`오류: ${error.message}`);
            } finally {
                // 버튼 상태 복원
                button.disabled = false;
                button.innerHTML = originalButtonHtml;
            }
        });
    });
});