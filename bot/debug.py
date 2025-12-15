# import google.generativeai as genai
# import os
# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# models = genai.list_models()
# for m in models:
#     # структура ответа может отличаться; выводим основные поля
#     print(m.get("name") if isinstance(m, dict) else getattr(m, 'name', m))
#     print(m)
#     print("----")


import requests
r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                 params={"key": "AIzaSyBsWctTXrQ6HR6G8HI4_ysWNy6UjGcB_7I"}, timeout=10)
print(r.status_code, r.text)