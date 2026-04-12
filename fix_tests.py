with open('tests/test_real_procurement_docs.py', 'r') as f:
    content = f.read()

# add OPENAI_API_KEY
import re
content = re.sub(
    r'def _submit_job\(client: TestClient, agent: str, text: str, filename: str\) -> str:',
    r'def _submit_job(client: TestClient, agent: str, text: str, filename: str) -> str:\n    import os\n    os.environ["OPENAI_API_KEY"] = "qwen32masterkey"',
    content
)

with open('tests/test_real_procurement_docs.py', 'w') as f:
    f.write(content)
