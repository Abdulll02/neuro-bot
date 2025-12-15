import requests
from config import Config
import tempfile
import os

class YandexTTS:
    def __init__(self):
        self.api_key = Config.YANDEX_API_KEY
        self.folder_id = Config.YANDEX_FOLDER_ID
        self.url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
    
    def synthesize(self, text, voice="alena", speed=1.0, emotion="good"):
        """Синтезирует речь из текста"""
        
        headers = {
            "Authorization": f"Api-Key {self.api_key}"
        }
        
        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": voice,
            "speed": speed,
            "emotion": emotion,
            "format": "mp3",
            "sampleRateHertz": 48000,
            "folderId": self.folder_id
        }
        
        response = requests.post(self.url, headers=headers, data=data, timeout=10)

        # Проверяем ответ
        if response.status_code == 200 and response.content:
            # Проверяем content-type: ожидаем аудио (mp3)
            content_type = response.headers.get('Content-Type', '')
            if 'audio' in content_type or 'mpeg' in content_type or content_type == 'application/octet-stream':
                return response.content
            else:
                # Сервер вернул не-аудио (возможен JSON с ошибкой)
                try:
                    err = response.json()
                except Exception:
                    err = response.text
                raise Exception(f"Yandex TTS returned unexpected content-type: {content_type}; detail={err}")
        else:
            # Пытаться получить json-ошибку, иначе вернуть текст
            try:
                err = response.json()
            except Exception:
                err = response.text
            raise Exception(f"Yandex TTS Error: status={response.status_code}, detail={err}")
    
    def create_audio_file(self, text, voice="alena", speed=1.0):
        """Создает временный аудиофайл"""
        audio_data = self.synthesize(text, voice, speed)

        if not audio_data:
            raise Exception("Yandex TTS returned empty audio data")

        # Создаем временный файл
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.write(audio_data)
        temp_file.close()

        return temp_file.name
    
    def get_available_voices(self):
        """Возвращает доступные голоса"""
        return list(Config.VOICES.keys())