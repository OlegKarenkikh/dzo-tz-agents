import requests
import json
import os

api_key = os.getenv("OPENAI_API_KEY", "qwen32masterkey")


def download_data():
    docs_dir = "real_docs"
    os.makedirs(docs_dir, exist_ok=True)

    with open(f"{docs_dir}/tz_example.txt", "w", encoding="utf-8") as f:
        f.write(
            "ТЕХНИЧЕСКОЕ ЗАДАНИЕ\nНа закупку ноутбуков для ИТ-отдела.\n1. Требуется 10 ноутбуков (Intel Core i7, 16GB RAM, 512GB SSD).\n2. Срок поставки: до 01.12.2024.\n3. Место поставки: г. Москва, ул. Ленина, д. 1.\n4. Гарантия: 1 год."
        )

    with open(f"{docs_dir}/dzo_example.txt", "w", encoding="utf-8") as f:
        f.write(
            "Заявка от ДЗО Ромашка\nПрошу согласовать закупку 10 ноутбуков по ТЗ в приложении.\nБюджет: 1 000 000 руб.\nСроки: до конца года."
        )

    # Creating ground truth
    ground_truth = {
        "dzo_example.txt": {
            "decision": "approved",
            "extracted_entities": {"item": "ноутбуки", "quantity": 10, "budget": "1 000 000 руб"},
        },
        "tz_example.txt": {
            "decision": "approved",
            "extracted_entities": {
                "item": "ноутбуки",
                "quantity": 10,
                "cpu": "Intel Core i7",
                "ram": "16GB",
                "storage": "512GB SSD",
                "delivery_date": "01.12.2024",
            },
        },
    }

    with open(f"ground_truth.json", "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    download_data()
