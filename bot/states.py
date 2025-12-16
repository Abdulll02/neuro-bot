from telegram.ext import ConversationHandler
import enum

class States(enum.Enum):
    WAITING_TEXT = 1
    WAITING_PHOTO = 2
    WAITING_CHAT = 3
    WAITING_QUESTION = 4
    WAITING_FILE = 5
    
# Для удобства
WAITING_TEXT, WAITING_PHOTO, WAITING_CHAT, WAITING_QUESTION, WAITING_FILE = range(5)