from telegram import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from config import Config

class Keyboards:
    @staticmethod
    def get_main_menu():
        """Главное меню"""
        keyboard = [
            [InlineKeyboardButton("💬 Чат с ИИ", callback_data="mode_chat")],
            [InlineKeyboardButton("🎤 Текст в голос", callback_data="mode_tts")],
            [InlineKeyboardButton("📷 Анализ фото", callback_data="mode_photo")],
            [InlineKeyboardButton("🎧 Настройки озвучки", callback_data="mode_settings")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_voice_selection():
        """Выбор голоса"""
        keyboard = []
        row = []
        for i, (voice_id, voice_name) in enumerate(Config.VOICES.items()):
            row.append(InlineKeyboardButton(voice_name, callback_data=f"voice_{voice_id}"))
            if (i + 1) % 2 == 0:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_speed_selection():
        """Выбор скорости"""
        keyboard = []
        for speed_id, (speed_name, _) in Config.SPEEDS.items():
            keyboard.append([InlineKeyboardButton(
                f"🎚️ {speed_name}", 
                callback_data=f"speed_{speed_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_tts_actions():
        """Действия после TTS"""
        keyboard = [
            [InlineKeyboardButton("⬅️ Главная", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_chat_actions():
        """Действия после ответа ИИ"""
        keyboard = [
            [InlineKeyboardButton("🎤 Озвучить ответ", callback_data="voice_response")],
            [InlineKeyboardButton("📝 Продолжить диалог", callback_data="continue_chat")],
            [InlineKeyboardButton("🗑️ Новый диалог", callback_data="new_chat")],
            [InlineKeyboardButton("⬅️ Главная", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_photo_actions():
        """Действия после анализа фото"""
        keyboard = [
            [InlineKeyboardButton("🎤 Озвучить результат", callback_data="voice_photo_result")],
            [InlineKeyboardButton("📷 Новое фото", callback_data="new_photo")],
            [InlineKeyboardButton("💬 Задать вопрос по фото", callback_data="ask_about_photo")],
            [InlineKeyboardButton("⬅️ Главная", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_settings():
        """Настройки озвучки"""
        keyboard = [
            [InlineKeyboardButton("🗣️ Выбрать голос", callback_data="set_voice")],
            [InlineKeyboardButton("🎚️ Настроить скорость", callback_data="set_speed")],
            [InlineKeyboardButton("⬅️ Главная", callback_data="back_to_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def get_cancel_button():
        """Кнопка отмены"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ])