import requests
import base64
import json
import io
import tempfile
import os
from typing import Optional, List, Dict, Any

from PIL import Image

from config import Config

# Импорты для локального парсинга документов (PyPDF2, docx) остаются.
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    
try:
    from docx import Document
    from io import BytesIO
    DOCX_SUPPORT = True
except ImportError:
    DOCX_SUPPORT = False


# Определяем глобальные заголовки
HEADERS = {
    "Authorization": f"Api-Key {Config.YANDEX_API_KEY}",
    "x-folder-id": Config.YANDEX_FOLDER_ID,
    "Content-Type": "application/json"
}


def post_process_math_output(text):
    # Удаляем $ в начале и конце формулы, или заменяем его
    text = text.replace('$', '')
    # Удаляем распространенные команды форматирования TeX
    text = text.replace('\\text{', '').replace('}', '')
    return text

# Используем то же имя класса, чтобы не менять bot.py
class GeminiAI: 
    def __init__(self):
        if not Config.YANDEX_API_KEY or not Config.YANDEX_FOLDER_ID:
            raise ValueError("Yandex API keys (API_KEY or FOLDER_ID) are missing in config.")

    def _no_format_prefix(self) -> str:
        # Максимально агрессивный запрет
        return (
            "На мой запрос отвечай только простым текстом. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать любые символы TeX, MathJax или Markdown (например, $, **, *, _, \\). "
            "Если нужно отобразить формулу, пиши ее в виде обычного текста без спецсимволов. "
            "Абзацы и переносы строк разрешены. Будь вежлив. Запрос: "
        )

    def _process_response(self, response_json: Dict[str, Any]) -> str:
        """Извлекает текст из стандартного ответа YandexGPT."""
        try:
            if 'result' in response_json and 'alternatives' in response_json['result']:
                text = response_json['result']['alternatives'][0]['message']['text']
                return text
            
            if 'error' in response_json:
                return f"Ошибка YandexGPT: {response_json['error'].get('message', 'Неизвестная ошибка')}"
            
            return "Ошибка: Не удалось получить ответ от ИИ."
        except Exception as e:
            return f"Ошибка парсинга ответа ИИ: {e}"

    # ===============================================
    # 1. ЧАТ (Text Generation)
    # ===============================================

    def chat(self, message: str, history: List[Dict[str, Any]] = None) -> str:
        """Обработка сообщений в режиме чата."""
        if history is None:
            history = []

        yandex_messages = []
        for m in history:
            role = m.get('role', 'user').lower()
            content = m.get('content', '')
            if content:
                yandex_messages.append({"role": role, "text": content})
        
        yandex_messages.append({"role": "user", "text": self._no_format_prefix() + message})

        last_exc = None
        
        for model in Config.YANDEX_TEXT_MODELS:
            payload = {
                "modelUri": f"gpt://{Config.YANDEX_FOLDER_ID}/{model}",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.6,
                    "maxTokens": "2000"
                },
                "messages": yandex_messages
            }

            try:
                response = requests.post(
                    url="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                    headers=HEADERS,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status() 
                response_text = self._process_response(response.json())
                return post_process_math_output(response_text)
            except requests.exceptions.HTTPError as e:
                try:
                    error_details = response.json()
                    detail_message = error_details.get('error', {}).get('message', 'No message provided')
                    # Отладочный вывод убран
                    last_exc = f"HTTP Error ({model}): {response.status_code}. Детали: {detail_message}"
                except Exception:
                    # Отладочный вывод убран
                    last_exc = f"HTTP Error ({model}): {response.status_code}. Нет деталей в JSON."
                continue 
            except Exception as e:
                last_exc = f"General Error ({model}): {e}"
                continue

        return f"Ошибка ИИ: Ни одна модель YandexGPT не смогла обработать запрос. Последняя ошибка: {last_exc}"

    # ===============================================
    # 2. АНАЛИЗ ИЗОБРАЖЕНИЙ (Vision OCR + GPT Text)
    # ===============================================

    def analyze_image(self, image_bytes: bytes, prompt: Optional[str] = None) -> str:
        """
        Анализирует изображение, используя Vision OCR для извлечения текста 
        и YandexGPT для анализа.
        """
        
        # --- Этап 0: Определение промпта и подготовка ---
        if not prompt:
            default_prompt = (
                "Проанализируй это изображение. Если это рукописный текст - перепиши его в печатном виде. "
                "Если это математический пример или задача - реши её и объясни решение. "
                "Если это что-то еще - опиши что видишь и дай рекомендации."
            )
        else:
            default_prompt = prompt
        
        # --- Этап 1: Извлекаем текст через Vision (OCR) ---
        # Отладочный print убран
        
        extracted_text = self._vision_ocr_extract(image_bytes, "temp_photo.jpeg") 
        
        if not extracted_text:
            return f"Ошибка анализа изображения: Yandex Vision OCR не смог извлечь текст. Проверьте активацию Vision API."
        
        # Отладочный print убран

        # --- Этап 2: Анализ текста с помощью YandexGPT ---
        
        # Формируем запрос для YandexGPT Text
        # System instruction обновлен для удаления лишнего форматирования
        system_instruction = (
            "Ты — аналитик изображений. Твоя задача — выполнить инструкцию пользователя на основе текста, извлеченного с изображения. "
            "Ответ должен быть без форматирования (кроме выделения кусков кода). "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать символы TeX/MathJax ($). " # Добавляем запрет сюда
            "Будь вежлив."
        )

        gpt_prompt = (
            f"Пользователь отправил изображение и попросил: '{default_prompt}'. "
            f"Текст, извлеченный с изображения, приводится ниже. Проанализируй его:\n\n"
            f"[ИЗВЛЕЧЕННЫЙ ТЕКСТ]\n{extracted_text}"
        )
        
        text_message = [
            {"role": "system", "text": system_instruction},
            {"role": "user", "text": gpt_prompt}
        ]
        
        last_fallback_exc = None
        
        for model in Config.YANDEX_ANALYSIS_MODELS: 
            payload = {
                "modelUri": f"gpt://{Config.YANDEX_FOLDER_ID}/{model}",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.3,
                    "maxTokens": "2000"
                },
                "messages": text_message
            }
            
            try:
                response = requests.post(
                    url="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                    headers=HEADERS,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                # Отладочный print убран
                response_text = self._process_response(response.json())
                return post_process_math_output(response_text)
            
            except requests.exceptions.HTTPError as e:
                try:
                    error_details = response.json()
                    detail_message = error_details.get('error', {}).get('message', 'No message provided')
                except Exception:
                    detail_message = 'No JSON body'
                last_fallback_exc = f"HTTP Error ({model}): {response.status_code}. Детали: {detail_message}"
                continue
            except Exception as e:
                last_fallback_exc = f"General Error ({model}): {e}"
                continue
        
        return f"Ошибка анализа изображения: GPT Text Analysis не сработал. Последняя ошибка: {last_fallback_exc}"

    # ===============================================
    # 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
    # ===============================================

    def _extract_text_from_file(self, file_bytes: bytes, file_name: str) -> Optional[str]:
        # ... (Код локального парсинга без изменений)
        text_payload = None
        
        # 1. TXT
        if file_name.lower().endswith('.txt'):
            try:
                text_payload = file_bytes.decode('utf-8')
            except Exception:
                try:
                    text_payload = file_bytes.decode('cp1251')
                except Exception:
                    pass
        # 2. PDF (требуется PyPDF2)
        elif file_name.lower().endswith('.pdf') and PDF_SUPPORT:
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                pages = [p.extract_text() or '' for p in reader.pages]
                text_payload = "\n".join(pages).strip()
            except Exception as e:
                text_payload = None
        # 3. DOCX (требуется python-docx)
        elif file_name.lower().endswith('.docx') and DOCX_SUPPORT:
            try:
                doc = Document(BytesIO(file_bytes))
                paras = [p.text for p in doc.paragraphs]
                text_payload = "\n".join(paras).strip()
            except Exception as e:
                text_payload = None

        return text_payload

    def _vision_ocr_extract(self, file_bytes: bytes, file_name: str) -> Optional[str]:
        """Извлекает текст из документа с помощью Yandex Vision OCR."""
        
        try:
            # 1. СТАНДАРТНОЕ Base64 кодирование
            file_base64 = base64.b64encode(file_bytes).decode('utf-8').strip()
            
            # 2. Определение MIME-типа (используем верхний регистр)
            mime_type = 'APPLICATION_OCTET_STREAM' 
            if file_name.lower().endswith('.pdf'):
                mime_type = 'PDF'
            elif file_name.lower().endswith(('.jpg', '.jpeg')):
                mime_type = 'JPEG'
            elif file_name.lower().endswith('.png'):
                mime_type = 'PNG'
            
            # --- СТРУКТУРА PAYLOAD ПО ДОКУМЕНТАЦИИ ---
            payload = {
                "mimeType": mime_type, 
                "languageCodes": ["ru", "en"], 
                "model": "page", 
                "content": file_base64
            }

            # >>> Блок вывода PAYLOAD DEBUG УДАЛЕН <<<
            
            response = requests.post(
                url="https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText",
                headers=HEADERS,
                json=payload,
                timeout=10
            )
            
            if response.status_code != 200:
                # Отладочный print убран
                return None 

            result = response.json()
            
            # --- Парсинг ответа Vision API ---
            extracted_text = ""
            
            # Пробуем извлечь текст из fullText, если есть
            if 'result' in result and 'textAnnotation' in result['result']:
                extracted_text = result['result']['textAnnotation'].get('fullText', '')
            
            # Если не fullText, используем детальный парсинг блоков (как Plan B)
            if not extracted_text:
                try:
                    for block in result.get('result', {}).get('textAnnotation', {}).get('blocks', []):
                        for line in block.get('lines', []):
                            extracted_text += line.get('text', '') + "\n"
                except Exception:
                    pass
                
            return extracted_text.strip()
        
        except Exception as e:
            # Отладочный print убран
            return None

    def analyze_document(self, file_bytes: bytes, file_name: str, prompt: Optional[str] = None) -> str:
        """
        Полный цикл анализа документа.
        """
        
        # Этап 1: Локальное извлечение
        extracted_text = self._extract_text_from_file(file_bytes, file_name)
        
        # Этап 2: Vision OCR (если локальное извлечение не удалось или это PDF/image)
        if not extracted_text:
            # Отладочный print убран
            if file_name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
                extracted_text = self._vision_ocr_extract(file_bytes, file_name)
            else:
                return "Ошибка анализа: Не удалось извлечь текст из файла. Для данного формата требуется локальный парсинг (PyPDF2/docx), который не сработал."


        if not extracted_text:
             return "Ошибка анализа: Yandex Vision не смог извлечь текст из документа."
        
        # Ограничение текста
        MAX_TEXT_LEN = 150000
        if len(extracted_text) > MAX_TEXT_LEN:
            # Отладочный print убран
            extracted_text = extracted_text[:MAX_TEXT_LEN]

        # Этап 3: Анализ текста с помощью YandexGPT (Актуальные модели и формат SYSTEM)
        
        if not prompt:
            prompt = (
                "Проанализируй этот документ. "
                "Если это текст - кратко суммаризируй основные моменты. "
                "Если это учебный материал - сделай краткий конспект. "
                "Если это данные/таблица - объясни что ты видишь. "
                "Будь краток и информативен."
            )
        
        # 1. Формируем системное сообщение (инструкцию)
        # System instruction обновлен для удаления лишнего форматирования
        system_instruction = (
            "Ты — аналитик документов. Твоя задача — выполнить инструкцию пользователя на основе предоставленного текста. "
            "Ответ должен быть без избыточного форматирования (кроме выделения кусков кода). "
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать символы TeX/MathJax ($). " # Добавляем запрет сюда
            "Будь вежлив."
        )

        # 2. Формируем пользовательское сообщение (запрос + текст документа)
        user_content = (
            f"Инструкция: {prompt}\n\n"
            f"--- Содержимое документа ---\n{extracted_text}\n"
        )
        
        # Используем стандартный формат с ролью 'system'
        text_message = [
            {"role": "system", "text": system_instruction},
            {"role": "user", "text": user_content}
        ]
        
        last_exc = None

        # Используем актуальные модели
        for model in Config.YANDEX_ANALYSIS_MODELS:
            payload = {
                "modelUri": f"gpt://{Config.YANDEX_FOLDER_ID}/{model}",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.3,
                    "maxTokens": "2000"
                },
                "messages": text_message
            }

            try:
                response = requests.post(
                    url="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                    headers=HEADERS,
                    json=payload,
                    timeout=10
                )
                response.raise_for_status()
                response_text = self._process_response(response.json())
                return post_process_math_output(response_text)

            except requests.exceptions.HTTPError as e:
                # ВЫВОД ДЕТАЛЕЙ ОШИБКИ 4xx/5xx
                try:
                    error_details = response.json()
                    detail_message = error_details.get('error', {}).get('message', 'No message provided')
                    # Отладочный print убран
                    last_exc = f"HTTP Error ({model}): {response.status_code}. Детали: {detail_message}"
                except Exception:
                    # Отладочный print убран
                    last_exc = f"HTTP Error ({model}): {response.status_code}. Нет деталей в JSON."
                continue
            except Exception as e:
                last_exc = f"General Error ({model}): {e}"
                continue

        return f"Ошибка анализа документа: Ни одна модель YandexGPT не смогла обработать запрос. Последняя ошибка: {last_exc}"