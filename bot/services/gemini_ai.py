import google.generativeai as genai
from PIL import Image
import io
from config import Config 

class GeminiAI:
    def __init__(self):
        genai.configure(api_key=Config.GEMINI_API_KEY)
        # Попробуем получить список доступных моделей и автоматически выбрать подходящую
        self.candidates = []
        self.model = None
        try:
            # Сначала попробуем закреплённую в конфиге модель, если она задана
            try:
                preferred = getattr(Config, 'GEMINI_MODEL', None)
                if preferred:
                    self.model = genai.GenerativeModel(preferred)
                    return
            except Exception:
                # не удалось инициализировать предпочитаемую модель — продолжим автоматический выбор
                self.model = None

            models = genai.list_models()
            # models может быть списком dict либо объектов; нормализуем
            norm = []
            for m in models:
                if isinstance(m, dict):
                    name = m.get('name')
                    methods = m.get('supportedGenerationMethods', [])
                else:
                    name = getattr(m, 'name', None)
                    methods = getattr(m, 'supportedGenerationMethods', []) or []
                if name and any(x in methods for x in ('generateContent', 'generate_content')):
                    # name обычно в виде 'models/gemini-2.5-flash' — возьмём короткую часть
                    short = name.split('/')[-1]
                    norm.append(short)

            # Приоритет предпочтительных моделей
            # Добавим в приоритет модель из конфига (если она указана), затем прочие
            priority = []
            cfg_model = getattr(Config, 'GEMINI_MODEL', None)
            if cfg_model:
                priority.append(cfg_model.split('/')[-1])
            priority.extend([
                'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-flash-latest', 'gemini-pro-latest',
                'gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemma-3-12b-it', 'text-bison-001'
            ])

            # Выбираем первую модель из priority, которая есть в norm; иначе берём первую из norm
            chosen = None
            for p in priority:
                if p in norm:
                    chosen = p
                    break
            if not chosen and norm:
                chosen = norm[0]

            if chosen:
                try:
                    self.model = genai.GenerativeModel(chosen)
                except Exception:
                    self.model = None
        except Exception:
            # Если list_models недоступен по каким-либо причинам — оставляем self.model = None
            self.model = None

    def _try_generate_with_model(self, model, prompt):
        """Пытается сгенерировать ответ с указанной моделью, возвращает response или пробрасывает исключение."""
        # Попытка использовать разные методы генерации в порядке предпочтения
        if hasattr(model, 'generate_content'):
            return model.generate_content(prompt)
        if hasattr(model, 'generate_text'):
            return model.generate_text(prompt)
        # Попытка вызвать через низкоуровневый интерфейс
        try:
            return genai.generate_text(model=model.name if hasattr(model, 'name') else model, prompt=prompt)
        except Exception:
            # пробрасываем исключение дальше
            raise
    
    def chat(self, message, history=None):
        """Обычный чат с ИИ"""
        try:
            if not self.model:
                return (
                    "Ошибка ИИ: не найдена доступная модель для генерации. "
                    "Проверьте правильность `GEMINI_API_KEY` и доступность моделей в вашем аккаунте."
                )
            # Некоторые версии клиента Gemini ожидают специальную структуру сообщений.
            # Чтобы избежать проблем с различными форматами, собираем текстовый prompt
            # из истории (_последние 10 сообщений_) и отправляем единый запрос.
            if history:
                prompt_lines = []
                for m in history[-10:]:
                    role = m.get('role', 'user')
                    content = m.get('content', '')
                    if role == 'user':
                        prompt_lines.append(f"User: {content}")
                    else:
                        prompt_lines.append(f"Assistant: {content}")

                # Добавляем текущий вопрос в конце
                prompt_lines.append(f"User: {message}\nAssistant:")
                prompt = "\n".join(prompt_lines)
                # Пытаемся сгенерировать ответ текущей моделью, при ошибке пробуем другие кандидаты
                try:
                    response = self._try_generate_with_model(self.model, prompt)
                except Exception as e:
                    last_exc = e
                    response = None
                    # На ошибку квоты добавляем запасные модели в список для попытки
                    err_text = str(e)
                    candidates_to_try = list(self.candidates)
                    if 'quota' in err_text.lower() or '429' in err_text:
                        fallback_models = [
                            'models/gemini-flash-lite-latest',
                            'models/gemini-2.5-flash-lite',
                            'models/gemma-3-1b-it',
                            'models/nano-banana-pro-preview'
                        ]
                        candidates_to_try = fallback_models + candidates_to_try
                    
                    for mname in candidates_to_try:
                        try:
                            candidate = genai.GenerativeModel(mname)
                            response = self._try_generate_with_model(candidate, prompt)
                            # Если получилось, закрепляем модель и выходим
                            self.model = candidate
                            break
                        except Exception as e2:
                            last_exc = e2
                            continue
                    if response is None:
                        raise last_exc
            else:
                try:
                    response = self._try_generate_with_model(self.model, message)
                except Exception as e:
                    last_exc = e
                    response = None
                    # На ошибку квоты добавляем запасные модели в список для попытки
                    err_text = str(e)
                    candidates_to_try = list(self.candidates)
                    if 'quota' in err_text.lower() or '429' in err_text:
                        fallback_models = [
                            'models/gemini-flash-lite-latest',
                            'models/gemini-2.5-flash-lite',
                            'models/gemma-3-1b-it',
                            'models/nano-banana-pro-preview'
                        ]
                        candidates_to_try = fallback_models + candidates_to_try
                    
                    for mname in candidates_to_try:
                        try:
                            candidate = genai.GenerativeModel(mname)
                            response = self._try_generate_with_model(candidate, message)
                            self.model = candidate
                            break
                        except Exception as e2:
                            last_exc = e2
                            continue
                    if response is None:
                        raise last_exc

            return response.text
        except Exception as e:
            return f"Ошибка ИИ: {str(e)}"
    
    def analyze_image(self, image_bytes, prompt=None):
        """Анализ изображения

        Попытка отправить изображение текущей модели; при ошибках квот
        пытаемся последовательно использовать запасные модели.
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))

            if not prompt:
                prompt = (
                    "Проанализируй это изображение. Если это рукописный текст - перепиши его в печатном виде. "
                    "Если это математический пример или задача - реши её и объясни решение. "
                    "Если это что-то еще - опиши что видишь и дай рекомендации."
                )

            # Основная попытка
            try:
                response = self.model.generate_content([prompt, image])
                return response.text
            except Exception as e:
                err_text = str(e)
                # На квотные/429 ошибки реагируем попыткой запасных моделей
                if 'quota' in err_text.lower() or 'quota exceeded' in err_text.lower() or '429' in err_text:
                    fallback_models = [
                        'models/gemini-flash-lite-latest',
                        'models/gemini-2.5-flash-image-preview',
                        'models/gemma-3-1b-it',
                        'models/nano-banana-pro-preview'
                    ]
                    last_exc = e
                    for fm in fallback_models:
                        try:
                            candidate = genai.GenerativeModel(fm)
                            resp = candidate.generate_content([prompt, image])
                            self.model = candidate
                            return resp.text
                        except Exception as e2:
                            last_exc = e2
                            continue
                    return f"Ошибка анализа изображения: {err_text} (запасные модели не помогли: {str(last_exc)})"
                # Иные ошибки — возвращаем сообщение об ошибке
                return f"Ошибка анализа изображения: {err_text}"
        except Exception as e:
            return f"Ошибка анализа изображения: {str(e)}"
    
    def analyze_pdf(self, pdf_bytes):
        """Анализ PDF файла (базовая поддержка)"""
        try:
            # Для PDF просто отправляем байты как текст
            prompt = "Проанализируй этот PDF документ. Если это учебный материал, сделай краткий конспект."
            response = self.model.generate_content([prompt, pdf_bytes])
            return response.text
        except Exception as e:
            return f"Ошибка анализа PDF: {str(e)}"