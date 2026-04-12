with open('tests/test_real_procurement_docs.py', 'r') as f:
    content = f.read()

import re
content = re.sub(
    r'def test_eek_tz_pipeline_accepted\(self, client\):',
    r'def test_eek_tz_pipeline_accepted(self, client, monkeypatch):\n        monkeypatch.setenv("OPENAI_API_KEY", "qwen32masterkey")',
    content
)

content = re.sub(
    r'def test_rbank_tz_pipeline_accepted\(self, client\):',
    r'def test_rbank_tz_pipeline_accepted(self, client, monkeypatch):\n        monkeypatch.setenv("OPENAI_API_KEY", "qwen32masterkey")',
    content
)

content = re.sub(
    r'def test_dzo_application_pipeline_accepted\(self, client\):',
    r'def test_dzo_application_pipeline_accepted(self, client, monkeypatch):\n        monkeypatch.setenv("OPENAI_API_KEY", "qwen32masterkey")',
    content
)

content = re.sub(
    r'def test_api_lists_submitted_jobs\(self, client\):',
    r'def test_api_lists_submitted_jobs(self, client, monkeypatch):\n        monkeypatch.setenv("OPENAI_API_KEY", "qwen32masterkey")',
    content
)

content = re.sub(
    r'def test_job_has_subject_preserved\(self, client\):',
    r'def test_job_has_subject_preserved(self, client, monkeypatch):\n        monkeypatch.setenv("OPENAI_API_KEY", "qwen32masterkey")',
    content
)

with open('tests/test_real_procurement_docs.py', 'w') as f:
    f.write(content)
