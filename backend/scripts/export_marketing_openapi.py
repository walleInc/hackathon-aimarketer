"""Export the workspace's implemented API and referenced schemas without removing planned APIs."""
import json
from pathlib import Path

from app.main import app


def export():
    full = app.openapi()
    paths = {path: operations for path, operations in full['paths'].items()
             if path.startswith(('/api/marketing/', '/api/analytics/')) or path.endswith('/metrics') or path == '/api/agent/message/reference'}
    needed = set()

    def refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == '$ref' and item.startswith('#/components/schemas/'):
                    needed.add(item.rsplit('/', 1)[1])
                else:
                    refs(item)
        elif isinstance(value, list):
            for item in value:
                refs(item)

    refs(paths)
    schemas = full['components']['schemas']
    resolved = {}
    while needed - resolved.keys():
        for name in sorted(needed - resolved.keys()):
            resolved[name] = schemas[name]
            refs(schemas[name])
    result = {'openapi': full['openapi'], 'info': {'title': 'AI-маркетолог — кабинет маркетолога', 'version': '1.0.0'},
              'security': [{'tma': []}], 'paths': paths,
              'components': {'securitySchemes': {'tma': {'type': 'apiKey', 'in': 'header', 'name': 'Authorization', 'description': 'tma <Telegram initData>; X-Dev-User only in dev mode'}}, 'schemas': resolved}}
    for path in paths.values():
        for operation in path.values():
            operation['x-status'] = 'implemented'
    target = Path(__file__).resolve().parents[2] / 'docs' / 'marketing-openapi.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    export()
