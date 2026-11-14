import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from app import agent, tg
from app.config import settings
from app.llm.openai_api import OpenAIProvider
from app.llm.stub import StubProvider
from app.media import media_path


def picture():
    out = io.BytesIO()
    Image.new('RGB', (256, 256), 'blue').save(out, 'PNG')
    return out.getvalue()


async def test_provider_sends_reference_to_edits(env, monkeypatch):
    edit = AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(picture()).decode())]))
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(images=SimpleNamespace(edit=edit))
    monkeypatch.setattr(settings, 'openai_image_model', 'black-forest-labs/flux-3-image-klein')
    url = await provider.generate_image('Новый фон', reference=picture())
    assert media_path(url).is_file()
    edit.assert_awaited_once_with(model='black-forest-labs/flux-3-image-klein', prompt='Новый фон', image=('reference.png', picture(), 'image/png'))


async def test_reference_reaches_image_generator(client, env, monkeypatch):
    provider = StubProvider()
    async def generate(prompt, reference=None):
        assert reference is not None
        with Image.open(io.BytesIO(reference)) as image:
            assert image.size == (256, 256)
        from app import post_images
        return post_images.save_upload(reference)
    provider.generate_image = AsyncMock(side_effect=generate)
    monkeypatch.setattr(agent, 'get_llm', lambda: provider)
    response = await client.post('/api/agent/message/reference', headers={'X-Dev-User': '101'}, data={'text': 'Создай пост о товаре'}, files={'reference': ('ref.png', picture(), 'image/png')})
    assert response.status_code == 200, response.text
    assert response.json()['post_id']
    provider.generate_image.assert_awaited_once()


async def test_invalid_reference_rejected_before_llm(client, monkeypatch):
    handle = AsyncMock()
    monkeypatch.setattr(agent, 'handle_message', handle)
    response = await client.post('/api/agent/message/reference', headers={'X-Dev-User': '101'}, data={'text': 'Создай пост'}, files={'reference': ('bad.png', b'invalid', 'image/png')})
    assert response.status_code == 422
    handle.assert_not_awaited()


async def test_telegram_member_can_attach_reference(env, monkeypatch):
    from app import runs
    from app.db import SessionLocal
    from app.models import AgentRun
    from sqlalchemy import select
    dispatch = AsyncMock()
    monkeypatch.setattr(runs, 'dispatch', dispatch)
    async def download(file, destination):
        destination.write(picture())
    message = SimpleNamespace(from_user=SimpleNamespace(id=101), media_group_id=None, caption='Создай пост', photo=[SimpleNamespace(file_size=100)], bot=SimpleNamespace(download=download), answer=AsyncMock())
    await tg.on_post_image(message)
    dispatch.assert_awaited_once()
    async with SessionLocal() as session:
        run = (await session.execute(select(AgentRun))).scalar_one()
        assert run.prompt == 'Создай пост' and run.status == 'queued'
        assert media_path(run.reference_url).is_file()
    assert 'Сообщу результат' in message.answer.await_args.args[0]


async def test_reference_failure_does_not_create_unrelated_card(client, monkeypatch):
    provider = StubProvider()
    provider.generate_image = AsyncMock(return_value=None)
    monkeypatch.setattr(agent, 'get_llm', lambda: provider)
    response = await client.post('/api/agent/message/reference', headers={'X-Dev-User': '101'}, data={'text': 'Создай пост'}, files={'reference': ('ref.png', picture(), 'image/png')})
    assert response.status_code == 422
    assert 'по референсу' in response.json()['detail']
    assert (await client.get('/api/posts', headers={'X-Dev-User': '101'})).json() == []


async def test_telegram_rejects_album(env, monkeypatch):
    handle = AsyncMock()
    monkeypatch.setattr(agent, 'handle_message', handle)
    message = SimpleNamespace(from_user=SimpleNamespace(id=101), media_group_id='album', answer=AsyncMock())
    await tg.on_post_image(message)
    handle.assert_not_awaited()
    assert 'без альбома' in message.answer.await_args.args[0]


async def test_async_reference_run_persists_input_and_result(client, monkeypatch):
    from app import post_images
    from app.db import SessionLocal
    from app.models import AgentRun
    provider = StubProvider()
    async def generate(prompt, reference=None):
        assert reference
        return post_images.save_upload(reference)
    provider.generate_image = AsyncMock(side_effect=generate)
    monkeypatch.setattr(agent, 'get_llm', lambda: provider)
    response = await client.post('/api/agent/runs/reference', headers={'X-Dev-User': '101'},
        data={'text': 'Создай пост о товаре'}, files={'reference': ('ref.png', picture(), 'image/png')})
    assert response.status_code == 202
    rid = response.json()['id']
    completed = (await client.get(f'/api/agent/runs/{rid}', headers={'X-Dev-User': '101'})).json()
    assert completed['status'] == 'completed' and completed['post_id'] and completed['image_url']
    async with SessionLocal() as session:
        run = await session.get(AgentRun, rid)
        assert media_path(run.reference_url).is_file()
