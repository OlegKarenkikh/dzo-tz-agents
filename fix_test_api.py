with open('tests/test_api.py', 'r') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'def test_invalid_result_type_rejected(self):' in line:
        lines[i+1] = '        ok, reason = _is_result_usable_for_agent("dzo", "not-a-dict")\n'
        lines[i+2] = '        assert ok is False\n'
        lines[i+3] = '        assert reason == "InvalidResultType"\n'
        break
with open('tests/test_api.py', 'w') as f:
    f.writelines(lines)
