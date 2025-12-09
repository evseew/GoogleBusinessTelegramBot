#!/usr/bin/env python3
"""
Тестовый скрипт для проверки доступных моделей OpenAI.
Использует API ключ из .env файла.
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

# Загружаем переменные из .env
load_dotenv()

# Создаём клиент (новый синтаксис OpenAI SDK v1.x)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

print("=" * 60)
print("Доступные модели OpenAI:")
print("=" * 60)

# Получаем список моделей
models = client.models.list()

# Сортируем по имени
sorted_models = sorted(models.data, key=lambda x: x.id)

# Фильтруем и выводим интересные модели (GPT, embeddings)
gpt_models = []
embedding_models = []
other_models = []

for model in sorted_models:
    model_id = model.id
    if "gpt" in model_id.lower():
        gpt_models.append(model_id)
    elif "embed" in model_id.lower():
        embedding_models.append(model_id)
    else:
        other_models.append(model_id)

print("\n🤖 GPT модели:")
print("-" * 40)
for m in gpt_models:
    print(f"  • {m}")

print(f"\n📊 Embedding модели:")
print("-" * 40)
for m in embedding_models:
    print(f"  • {m}")

print(f"\n📋 Другие модели ({len(other_models)} шт.):")
print("-" * 40)
# Показываем только первые 20, чтобы не засорять вывод
for m in other_models[:20]:
    print(f"  • {m}")
if len(other_models) > 20:
    print(f"  ... и ещё {len(other_models) - 20} моделей")

print("\n" + "=" * 60)
print(f"Всего моделей: {len(sorted_models)}")
print(f"  - GPT: {len(gpt_models)}")
print(f"  - Embeddings: {len(embedding_models)}")
print(f"  - Другие: {len(other_models)}")
print("=" * 60)

