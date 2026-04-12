import os
import json

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

print("done")
