import json
from unittest.mock import patch

from agent21_tender_inspector.tools import generate_document_list
from agent21_tender_inspector.tools import invoke_peer_agent


class TestGenerateDocumentList:
    def test_full_document_list(self):
        payload = json.dumps({
            "procurement_subject": "Строительство объекта",
            "documents": [
                {
                    "name": "Копия лицензии на строительную деятельность",
                    "type": "лицензия",
                    "mandatory": True,
                    "section_reference": "Раздел 3.2, п. 3.2.1",
                    "requirements": "Нотариально заверенная копия, действующая на дату подачи",
                    "basis": "Прямое требование",
                },
                {
                    "name": "Свидетельство о членстве в СРО",
                    "type": "свидетельство",
                    "mandatory": True,
                    "section_reference": "Раздел 2.5",
                    "requirements": "Действующее на дату подачи заявки",
                    "basis": "Вытекает из предмета закупки (строительные работы)",
                },
                {
                    "name": "Банковская гарантия обеспечения заявки",
                    "type": "гарантия",
                    "mandatory": False,
                    "section_reference": "Раздел 5.1",
                    "requirements": "Оформлена банком из перечня Министерства финансов",
                    "basis": "Прямое требование",
                },
            ],
        })
        result = json.loads(generate_document_list.invoke(payload))
        assert result["procurement_subject"] == "Строительство объекта"
        assert result["summary"]["total"] == 3
        assert result["summary"]["mandatory"] == 2
        assert result["summary"]["conditional"] == 1
        assert len(result["documents"]) == 3
        assert "timestamp" in result
        # Проверяем нормализацию
        first = result["documents"][0]
        assert first["id"] == 1
        assert first["name"] == "Копия лицензии на строительную деятельность"
        assert first["type"] == "лицензия"
        assert first["mandatory"] is True

    def test_empty_documents(self):
        payload = json.dumps({
            "procurement_subject": "Поставка оборудования",
            "documents": [],
        })
        result = json.loads(generate_document_list.invoke(payload))
        assert result["summary"]["total"] == 0
        assert result["summary"]["mandatory"] == 0
        assert result["summary"]["conditional"] == 0
        assert result["documents"] == []

    def test_mandatory_string_false(self):
        """Обязательность может передаваться строкой."""
        payload = json.dumps({
            "procurement_subject": "Аренда оборудования",
            "documents": [
                {
                    "name": "Страховой полис",
                    "type": "иное",
                    "mandatory": "условный",
                    "section_reference": "п. 4.3",
                    "requirements": "Покрытие не менее 1 млн руб.",
                    "basis": "Прямое требование",
                },
            ],
        })
        result = json.loads(generate_document_list.invoke(payload))
        assert result["documents"][0]["mandatory"] is False
        assert result["summary"]["conditional"] == 1

    def test_unknown_type_normalized_to_inoe(self):
        """Неизвестный тип документа нормализуется в 'иное'."""
        payload = json.dumps({
            "procurement_subject": "Поставка ПО",
            "documents": [
                {
                    "name": "Технический паспорт",
                    "type": "неизвестный_тип",
                    "mandatory": True,
                    "section_reference": "п. 2.1",
                    "requirements": "",
                    "basis": "Прямое требование",
                },
            ],
        })
        result = json.loads(generate_document_list.invoke(payload))
        assert result["documents"][0]["type"] == "иное"

    def test_missing_document_name_auto_filled(self):
        """Если имя документа не указано, автоматически присваивается."""
        payload = json.dumps({
            "procurement_subject": "Услуги охраны",
            "documents": [
                {
                    "type": "лицензия",
                    "mandatory": True,
                    "section_reference": "п. 1.1",
                    "requirements": "Действующая лицензия",
                    "basis": "Прямое требование",
                },
            ],
        })
        result = json.loads(generate_document_list.invoke(payload))
        assert result["documents"][0]["name"] == "Документ 1"

    def test_invalid_json_input(self):
        """Невалидный JSON создаёт скелет результата без ошибки."""
        result = json.loads(generate_document_list.invoke("!!!"))
        # При не-JSON input создаётся скелет
        assert "documents" in result
        assert result["documents"] == []

    def test_empty_query(self):
        """Пустой запрос возвращает ошибку."""
        result = json.loads(generate_document_list.invoke(""))
        assert "error" in result

    def test_document_ids_sequential(self):
        """ID документов должны быть последовательными, начиная с 1."""
        payload = json.dumps({
            "procurement_subject": "ИТ-услуги",
            "documents": [
                {"name": "Копия устава", "type": "устав", "mandatory": True,
                 "section_reference": "п. 3.1", "requirements": "", "basis": "Прямое требование"},
                {"name": "Копия ИНН", "type": "копия", "mandatory": True,
                 "section_reference": "п. 3.2", "requirements": "", "basis": "Прямое требование"},
                {"name": "Справка об отсутствии задолженности", "type": "справка",
                 "mandatory": False, "section_reference": "п. 3.3", "requirements": "",
                 "basis": "Прямое требование"},
            ],
        })
        result = json.loads(generate_document_list.invoke(payload))
        ids = [doc["id"] for doc in result["documents"]]
        assert ids == [1, 2, 3]

    def test_all_document_types_accepted(self):
        """Все допустимые типы документов принимаются без изменений."""
        valid_types = [
            "лицензия", "свидетельство", "копия", "оригинал", "форма",
            "декларация", "гарантия", "выписка", "справка", "сертификат",
            "договор", "протокол", "приказ", "устав", "иное",
        ]
        for doc_type in valid_types:
            payload = json.dumps({
                "procurement_subject": "Тест",
                "documents": [
                    {"name": f"Документ типа {doc_type}", "type": doc_type,
                     "mandatory": True, "section_reference": "п. 1",
                     "requirements": "", "basis": "Прямое требование"},
                ],
            })
            result = json.loads(generate_document_list.invoke(payload))
            assert result["documents"][0]["type"] == doc_type, f"Тип {doc_type!r} должен приниматься"


class TestInvokePeerAgent:
    @patch("agent21_tender_inspector.tools.invoke_agent_as_tool")
    def test_success(self, mock_invoke):
        mock_invoke.return_value = {
            "output": "ok",
            "observations": [{"overall_status": "Соответствует"}],
            "intermediate_steps": [],
        }
        payload = json.dumps({
            "target_agent": "tz",
            "query_text": "Проверь ТЗ",
            "subject": "Тема",
            "sender": "x@y.com",
        })
        result = json.loads(invoke_peer_agent.invoke(payload))
        assert result["peerAgentResult"]["target_agent"] == "tz"
        assert result["peerAgentResult"]["output"] == "ok"

    def test_requires_json(self):
        result = json.loads(invoke_peer_agent.invoke("not-json"))
        assert "error" in result

    def test_requires_required_fields(self):
        result = json.loads(invoke_peer_agent.invoke(json.dumps({"target_agent": "tz"})))
        assert "error" in result
