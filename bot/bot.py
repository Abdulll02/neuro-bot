import logging
import os
from datetime import datetime
import traceback
import json
import google.generativeai as genai
from telegram import Update, InputFile
from telegram.error import BadRequest
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.error import TelegramError

from config import Config
from services.yandex_tts import YandexTTS
from services.gemini_ai import GeminiAI
from keyboards import Keyboards
from utils import temp_audio_file, split_long_message, format_voice_info, convert_mp3_to_ogg_opus
from states import WAITING_TEXT, WAITING_PHOTO, WAITING_CHAT, WAITING_QUESTION, WAITING_FILE

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def safe_edit_message(query, text, **kwargs):
    """Пытается отредактировать текст сообщения, если это невозможно — отправляет новое сообщение.

    kwargs могут содержать parse_mode и reply_markup.
    """
    try:
        return await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        # Обрабатываем ошибки редактирования — в том числе parse-entity ошибки
        msg = str(e)
        # Если проблема — отсутствие текстового содержимого для редактирования
        if "There is no text in the message to edit" in msg or "message to edit" in msg:
            # Если у сообщения есть подпись (caption), попробуем отредактировать подпись
            try:
                if query.message and getattr(query.message, 'caption', None) is not None:
                    return await query.message.edit_caption(caption=text, **{k: v for k, v in kwargs.items() if k != 'parse_mode'})
            except Exception:
                pass

            # В противном случае отправляем новое сообщение и пробуем убрать клавиатуру у старого
            try:
                await query.message.reply_text(text, **{k: v for k, v in kwargs.items() if k != 'parse_mode'})
            except Exception:
                # как последний инструмент — ответ на callback
                await query.answer(text)
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return None
        # Если проблема — парсинг entities (незакрытые/несоответствующие отступы в Markdown)
        if "can't find end of the entity" in msg or "Can't parse entities" in msg or "can't find end of the entity" in msg.lower():
            # Попытка повторить без parse_mode
            try:
                return await query.edit_message_text(text, **{k: v for k, v in kwargs.items() if k != 'parse_mode'})
            except Exception:
                try:
                    await query.message.reply_text(text)
                except Exception:
                    await query.answer(text)
                return None

        # Прочие ошибки пробрасываем
        raise


async def safe_reply(message_obj, text, parse_mode='Markdown', **kwargs):
    """Безопасная отправка текста: пытается с указанным parse_mode, при ошибке парсинга entities повторяет без parse_mode."""
    try:
        return await message_obj.reply_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "can't find end of the entity" in err or "Can't parse entities" in err or "can't find end of the entity" in err.lower():
            # Повтор без parse_mode
            try:
                return await message_obj.reply_text(text, **{k: v for k, v in kwargs.items() if k != 'parse_mode'})
            except Exception:
                return await message_obj.reply_text(text)
        raise

# Инициализация сервисов
tts_service = YandexTTS()
ai_service = GeminiAI()

# Хранение состояния пользователей
user_data = {}

# ========== КОМАНДЫ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Инициализация данных пользователя
    user_data[user_id] = {
        'mode': 'chat',
        'voice': 'alena',
        'speed': 1.0,
        'chat_history': [],
        'last_tts_text': '',
        'last_photo_analysis': ''
    }
    
    welcome_text = """👋 *Добро пожаловать в Учебного Бота!*
    
Я умею:
• 💬 *Общаться как ИИ-ассистент* - отвечаю на вопросы, даю советы
• 🎤 *Преобразовывать текст в речь* - с разными голосами и скоростью
• 📷 *Анализировать фотографии* - читаю рукописный текст, решаю примеры
• 📄  *Работать с файлами* - анализирую и конспектирую текстовые документы

*Подсказка:* Используй команду /help для получения справки

Выберите режим работы:"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=Keyboards.get_main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """📚 *Помощь по использованию бота*
    
*Основные возможности:*
1. *💬 Чат с ИИ* - просто отправьте текстовое сообщение
2. *🎤 Текст в голос* - выберите режим и введите текст для озвучки
3. *📷 Анализ фото* - отправьте фото с текстом или примером (Можете добавить запрос подписав фото)
4. *📄 Работа с файлами* - отправьте текстовый файл с запросом для анализа и действий (*Поддерживает только TXT, DOCX, PDF*)

*Управление:*
• Используйте кнопки для навигации
• Можно настраивать голос и скорость речи
• Для отмены действия - кнопка "❌ Отмена"

*Советы:*
• Для математических задач - отправьте фото примера
• Для медленного изучения - используйте скорость 0.5-0.8
• Разные голоса помогают лучше концентрироваться"""
    
    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=Keyboards.get_main_menu()
    )

# ========== ОБРАБОТЧИКИ РЕЖИМОВ ==========

async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора режима"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    # Ensure user data exists (avoid KeyError if /start wasn't called)
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'chat',
            'voice': 'alena',
            'speed': 1.0,
            'chat_history': [],
            'last_tts_text': '',
            'last_photo_analysis': ''
        }
    mode = query.data.replace("mode_", "")
    
    user_data[user_id]['mode'] = mode
    
    if mode == "chat":
        await safe_edit_message(query,
            "💬 *Режим: Чат с ИИ*\n\nОтправьте ваш вопрос или сообщение. "
            "ИИ ответит и поможет с учебными задачами.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_CHAT
        
    elif mode == "tts":
        await safe_edit_message(query,
            "🎤 *Режим: Текст в голос*\n\nОтправьте текст, который нужно озвучить. "
            f"\n\n{format_voice_info(user_data[user_id]['voice'], user_data[user_id]['speed'])}",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_TEXT
        
    elif mode == "photo":
        await safe_edit_message(query,
            "📷 *Режим: Анализ фото*\n\nОтправьте фото с:\n"
            "• Рукописным текстом (переведу в печатный)\n"
            "• Математическим примером (решу и объясню)\n"
            "• Учебным материалом (проанализирую)",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_PHOTO
        
    elif mode == "file":
        await safe_edit_message(query,
            "📄 *Режим: Работа с файлами*\n\nОтправьте файл (PDF, TXT, DOCX) с опциональной подписью-запросом.\n"
            "Я проанализирую содержимое файла.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_FILE
        
    elif mode == "settings":
        await safe_edit_message(query,
            "🎧 *Настройки озвучки*\n\nВыберите параметр для настройки:",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_settings()
        )

# ========== ОБРАБОТКА ТЕКСТА (TTS) ==========

async def handle_text_for_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста для озвучки"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if not text.strip():
        await update.message.reply_text("Пожалуйста, отправьте текст для озвучки.")
        return WAITING_TEXT
    
    # Сохраняем текст
    user_data[user_id]['last_tts_text'] = text
    
    # Показываем статус
    status_msg = await update.message.reply_text(
        "🔊 *Синтезирую речь...*",
        parse_mode='Markdown'
    )
    
    try:
        # Синтезируем речь
        voice = user_data[user_id]['voice']
        speed = user_data[user_id]['speed']
        audio_data = tts_service.synthesize(text, voice=voice, speed=speed)
        
        # Отправляем аудио
        with temp_audio_file(audio_data) as audio_path:
            # Попытка конвертировать mp3 -> ogg/opus и отправить как voice (лучше совместимо с Telegram)
            ogg_path = convert_mp3_to_ogg_opus(audio_path)
            if ogg_path:
                try:
                    with open(ogg_path, 'rb') as f_ogg:
                        await update.message.reply_voice(
                            voice=InputFile(f_ogg, filename='audio.ogg'),
                            caption=f"🎤 Озвученный текст\n\n{format_voice_info(voice, speed)}",
                            reply_markup=Keyboards.get_tts_actions()
                        )
                finally:
                    try:
                        os.unlink(ogg_path)
                    except Exception:
                        pass
            else:
                with open(audio_path, 'rb') as f_mp3:
                    await update.message.reply_audio(
                        audio=InputFile(f_mp3, filename='audio.mp3'),
                        caption=f"🎤 Озвученный текст\n\n{format_voice_info(voice, speed)}",
                        reply_markup=Keyboards.get_tts_actions()
                    )
        
        # Удаляем статус
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"TTS error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка синтеза речи: {str(e)}",
            reply_markup=Keyboards.get_main_menu()
        )
        return ConversationHandler.END
    
    return ConversationHandler.END

# ========== ОБРАБОТКА ФОТО ==========

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фотографий"""
    user_id = update.effective_user.id
    
    # Показываем статус
    status_msg = await update.message.reply_text(
        "🔍 *Анализирую изображение...*",
        parse_mode='Markdown'
    )
    
    try:
        # Получаем фото наибольшего размера
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Если у фото есть подпись — используем её как пользовательский запрос/промпт
        caption = update.message.caption if getattr(update.message, 'caption', None) else None
        # Анализируем фото через Gemini, передавая подпись как prompt (если есть)
        analysis_result = ai_service.analyze_image(photo_bytes, prompt=caption)
        
        # Сохраняем результат
        user_data[user_id]['last_photo_analysis'] = analysis_result
        
        # Разбиваем длинный текст если нужно
        message_parts = split_long_message(analysis_result)

        # Отправляем первую часть с клавиатурой, используя safe_reply
        await safe_reply(update.message, f"📷 *Результат анализа:*\n\n{message_parts[0]}", parse_mode='Markdown', reply_markup=Keyboards.get_photo_actions())
        
        # Отправляем остальные части если есть
        for part in message_parts[1:]:
            await update.message.reply_text(part)
        
        # Удаляем статус
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Photo analysis error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка анализа фото: {str(e)}",
            reply_markup=Keyboards.get_main_menu()
        )
    
    return ConversationHandler.END

# ========== ОБРАБОТКА ФАЙЛОВ ==========

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка документов (PDF, TXT, DOCX и т.д.)"""
    user_id = update.effective_user.id
    
    # Инициализация данных пользователя если нужно
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'chat',
            'voice': 'alena',
            'speed': 1.0,
            'chat_history': [],
            'last_tts_text': '',
            'last_photo_analysis': ''
        }
    
    # Показываем статус
    status_msg = await update.message.reply_text(
        "📄 *Анализирую файл...*",
        parse_mode='Markdown'
    )
    
    try:
        # Получаем документ
        document_file = await update.message.document.get_file()
        file_bytes = await document_file.download_as_bytearray()
        file_name = update.message.document.file_name or "document"
        
        # Если у файла есть подпись — используем её как промпт
        caption = update.message.caption if getattr(update.message, 'caption', None) else None
        
        # Анализируем файл через Gemini (использует Files API)
        analysis_result = ai_service.analyze_document(file_bytes, file_name, prompt=caption)
        
        # Сохраняем результат
        user_data[user_id]['last_file_analysis'] = analysis_result
        
        # Разбиваем длинный текст если нужно
        message_parts = split_long_message(analysis_result)
        
        # Отправляем первую часть с клавиатурой
        await safe_reply(update.message, f"📄 *Результат анализа:*\n\n{message_parts[0]}", parse_mode='Markdown', reply_markup=Keyboards.get_file_actions())
        
        # Отправляем остальные части если есть
        for part in message_parts[1:]:
            await update.message.reply_text(part)
        
        # Удаляем статус
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Document analysis error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка анализа файла: {str(e)}",
            reply_markup=Keyboards.get_main_menu()
        )
    
    return ConversationHandler.END

# ========== ОБРАБОТКА ЧАТА С ИИ ==========

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений в режиме чата"""
    user_id = update.effective_user.id
    message = update.message.text
    
    # Показываем статус
    status_msg = await update.message.reply_text(
        "🤖 *ИИ думает...*",
        parse_mode='Markdown'
    )
    
    try:
        # Добавляем сообщение в историю
        if 'chat_history' not in user_data[user_id]:
            user_data[user_id]['chat_history'] = []
        
        user_data[user_id]['chat_history'].append({
            'role': 'user',
            'content': message,
            'timestamp': datetime.now()
        })
        
        # Получаем ответ от ИИ
        response = ai_service.chat(message, user_data[user_id]['chat_history'])
        
        # Добавляем ответ в историю
        user_data[user_id]['chat_history'].append({
            'role': 'assistant',
            'content': response,
            'timestamp': datetime.now()
        })
        
        # Ограничиваем историю
        if len(user_data[user_id]['chat_history']) > 20:
            user_data[user_id]['chat_history'] = user_data[user_id]['chat_history'][-10:]
        
        # Разбиваем длинный ответ если нужно (Telegram лимит ~4096 символов)
        message_parts = split_long_message(response)
        
        # Отправляем первую часть с клавиатурой
        await safe_reply(update.message, f"🤖 *ИИ:*\n\n{message_parts[0]}", parse_mode='Markdown', reply_markup=Keyboards.get_chat_actions())
        
        # Отправляем остальные части если есть
        for part in message_parts[1:]:
            await update.message.reply_text(part)
        
        # Удаляем статус
        await status_msg.delete()
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        await update.message.reply_text(
            f"❌ Ошибка ИИ: {str(e)}",
            reply_markup=Keyboards.get_main_menu()
        )
    
    return WAITING_CHAT

# ========== ОБРАБОТЧИКИ КНОПОК ==========

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех callback-кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = query.data
    
    # Инициализация данных пользователя если нужно
    if user_id not in user_data:
        user_data[user_id] = {
            'mode': 'chat',
            'voice': 'alena',
            'speed': 1.0,
            'chat_history': [],
            'last_tts_text': '',
            'last_photo_analysis': ''
        }
    
    # Обработка действий
    if action == "back_to_main":
        await safe_edit_message(query,
            "👋 *Главное меню*\n\nВыберите режим работы:",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_main_menu()
        )
    
    elif action == "cancel":
        await safe_edit_message(query,
            "❌ Действие отменено.",
            reply_markup=Keyboards.get_main_menu()
        )
    
    elif action.startswith("voice_"):
        # Выбор голоса
        voice_id = action.replace("voice_", "")
        user_data[user_id]['voice'] = voice_id
        
        await safe_edit_message(query,
            f"✅ Голос изменен на: *{Config.VOICES.get(voice_id, voice_id)}*",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_settings()
        )
    
    elif action.startswith("speed_"):
        # Выбор скорости
        speed_id = action.replace("speed_", "")
        # Если callback пришел из меню выбора скорости, speed_id будет в Config.SPEEDS
        if speed_id in Config.SPEEDS:
            user_data[user_id]['speed'] = Config.SPEEDS[speed_id][1]

            await safe_edit_message(query,
                f"✅ Скорость изменена на: *{Config.SPEEDS[speed_id][0]}*",
                parse_mode='Markdown',
                reply_markup=Keyboards.get_settings()
            )
        else:
            # Неизвестный сабкомандный суффикс (например 'up' или 'down') — логируем и игнорируем
            logger.warning(f"Unhandled speed action: {action}")
    
    # 'repeat_tts' handler removed — TTS repeat button was eliminated from UI.
    
    elif action == "slow_down":
        # Замедление
        user_data[user_id]['speed'] = max(0.1, user_data[user_id]['speed'] - 0.2)
        await safe_edit_message(query,
            f"🐌 Скорость уменьшена до: *{user_data[user_id]['speed']}x*",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_tts_actions()
        )
    
    elif action == "speed_up":
        # Ускорение
        user_data[user_id]['speed'] = min(3.0, user_data[user_id]['speed'] + 0.2)
        await safe_edit_message(query,
            f"⚡ Скорость увеличена до: *{user_data[user_id]['speed']}x*",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_tts_actions()
        )
    
    # note: 'voice_response' handler intentionally removed — TTS-on-demand button caused bugs and
    # was outside the original spec. If future TTS-on-demand is required, reintroduce here with
    # proper safeguards and rate/size checks.
    
    # note: 'voice_photo_result' handler removed — TTS-on-photo-result button caused bugs and
    # was outside the requested spec. If needed later, reintroduce with proper safeguards.
    
    elif action == "set_voice":
        await safe_edit_message(query,
            "🗣️ *Выберите голос:*",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_voice_selection()
        )
    
    elif action == "set_speed":
        await safe_edit_message(query,
            "🎚️ *Выберите скорость:*",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_speed_selection()
        )
    
    elif action == "new_tts":
        await safe_edit_message(query,
            "🎤 *Режим: Текст в голос*\n\nОтправьте текст для озвучки.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_TEXT
    
    elif action == "new_photo":
        await safe_edit_message(query,
            "📷 *Режим: Анализ фото*\n\nОтправьте новое фото для анализа.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        try:
            await query.answer(text="Отправьте новое фото")
        except Exception:
            pass
        return WAITING_PHOTO
    
    elif action == "new_file":
        await safe_edit_message(query,
            "📄 *Режим: Работа с файлами*\n\nОтправьте новый файл для анализа.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        try:
            await query.answer(text="Отправьте новый файл")
        except Exception:
            pass
        return WAITING_FILE
    
    elif action == "continue_chat":
        await safe_edit_message(query,
            "💬 *Режим: Чат с ИИ*\n\nПродолжайте диалог.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_CHAT
    
    elif action == "new_chat":
        user_data[user_id]['chat_history'] = []
        await safe_edit_message(query,
            "💬 *Новый диалог*\n\nИстория очищена. Задайте новый вопрос.",
            parse_mode='Markdown',
            reply_markup=Keyboards.get_cancel_button()
        )
        return WAITING_CHAT

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def main():
    """Запуск бота"""
    if not Config.TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN не установлен в .env файле")
    
    # Создаем приложение
    application = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    # Global photo handler: accept photos even if conversation state wasn't set
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    # Global document handler: accept documents even if conversation state wasn't set
    application.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_document))
    
    # Conversation Handler для режимов
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_mode_selection, pattern="^mode_")
        ],
        states={
            WAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_for_tts),
                CallbackQueryHandler(handle_callback, pattern="^cancel$")
            ],
            WAITING_PHOTO: [
                MessageHandler(filters.PHOTO, handle_photo),
                CallbackQueryHandler(handle_callback, pattern="^cancel$")
            ],
            WAITING_FILE: [
                MessageHandler(filters.Document.ALL, handle_document),
                CallbackQueryHandler(handle_callback, pattern="^cancel$")
            ],
            WAITING_CHAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message),
                CallbackQueryHandler(handle_callback, pattern="^cancel$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(handle_callback, pattern="^back_to_main$"),
            CallbackQueryHandler(handle_callback, pattern="^cancel$")
        ],
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    
    # Обработчики callback-кнопок
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
    