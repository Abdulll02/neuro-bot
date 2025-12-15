from telegram.ext import ConversationHandler
import enum

class States(enum.Enum):
    WAITING_TEXT = 1
    WAITING_PHOTO = 2
    WAITING_CHAT = 3
    WAITING_QUESTION = 4
    
# Для удобства
WAITING_TEXT, WAITING_PHOTO, WAITING_CHAT, WAITING_QUESTION = range(4)