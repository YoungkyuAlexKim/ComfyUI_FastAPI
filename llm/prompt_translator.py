from llama_cpp import Llama
import os


class PromptTranslator:
    def __init__(self, model_path="models/gemma-2-4b-it-q8_0.gguf"):
        """
        Gemma GGUF 모델을 로드하여 프롬프트 번역기 초기화
        """
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {model_path}")

        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=-1,  # GPU를 모두 사용 (-1), CPU만 사용 시 0
            n_ctx=2048,       # 컨텍스트 크기
            verbose=False     # 자세한 로그 비활성화
        )

    def translate_to_danbooru(self, text: str) -> str:
        """
        주어진 자연어 텍스트를 Danbooru 태그로 변환
        """
        system_prompt = (
            "You are an expert in creating high-quality, detailed image generation prompts "
            "using Danbooru tags. Your task is to convert the user's natural language "
            "description into a comma-separated list of Danbooru tags. Only include "
            "relevant tags and do not add any extra explanations or sentences."
        )

        prompt = f"""
<start_of_turn>user
Please convert the following sentence into Danbooru tags:
'{text}'<end_of_turn>
<start_of_turn>model
"""

        full_prompt = f"{system_prompt}\n{prompt}"

        try:
            output = self.llm(
                full_prompt,
                max_tokens=512,
                stop=["<end_of_turn>", "user", "model"],
                echo=False,
                temperature=0.2,
            )
            
            # 생성된 텍스트에서 불필요한 부분 정리
            result = output['choices'][0]['text'].strip()
            # 혹시 모를 추가 설명 제거 (첫 줄만 사용)
            result = result.split('\n')[0]
            # 태그가 아닌 불필요한 단어 제거
            result = result.replace("Danbooru tags:", "").strip()

            return result

        except Exception as e:
            print(f"LLM 생성 중 오류 발생: {e}")
            return "Error: Could not generate tags."