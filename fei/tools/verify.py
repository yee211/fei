from fei.tools.base import Tool
from fei.project_verify import verify_project,guard

tool=Tool("verify_project","Run selected configured test/lint/build checks from workdir .fei.json; omitted checks runs all. Shows exact argv for permission approval. Configuration version=1, checks maps names to category, argv and optional timeout. {python} resolves to current interpreter. No inferred commands. Results and actual call ID can be referenced by finish_task.",{"type":"object","properties":{"checks":{"type":"array","items":{"type":"string","minLength":1},"minItems":1,"maxItems":20}},"additionalProperties":False},verify_project,guard=guard)
