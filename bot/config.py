import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    
    # Yandex SpeechKit
    YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
    YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
    
    # Gemini AI
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    
    # Настройки голосов
    VOICES = {
        "alena": "Алена (женский)",
        "filipp": "Филипп (мужской)",
        "jane": "Джейн (женский)",
        "omazh": "Омаж (женский)",
        "zahar": "Захар (мужской)"
    }
    
    # Настройки скорости
    SPEEDS = {
        "very_slow": ("Очень медленно", 0.5),
        "slow": ("Медленно", 0.8),
        "normal": ("Нормально", 1.0),
        "fast": ("Быстро", 1.3),
        "very_fast": ("Очень быстро", 1.8)
    }
