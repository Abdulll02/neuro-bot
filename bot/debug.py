import requests

# Тот же ключ и folder_id что для SpeechKit!
api_key = "AQVNz3w-oRdgEqjwF32HrvceX2Hu_oBHqhPIf5_C"
folder_id = "b1ghr59j6j65hu2r5q5p"

response = requests.post(
    url="https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
    headers={
        "Authorization": f"Api-Key {api_key}",
        "x-folder-id": folder_id
    },
    json={
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",  # Бесплатная модель
        "messages": [{"role": "user", "text": "Привет! Ответь коротко."}]
    }
)

print(response.json())