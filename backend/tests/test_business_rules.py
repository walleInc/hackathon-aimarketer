"""Бизнес-правила: лимиты, редактирование знаний, бренд-кит и проверка загружаемых файлов."""
import io

from PIL import Image
from sqlalchemy import select

from app import branding
from app.db import SessionLocal
from app.models import Company, KnowledgeDoc, Post, UsageCost
from tests.conftest import as_user

ADMIN = as_user(1)


async def test_knowledge_can_be_edited(client, env):
    r = await client.post(f"/api/admin/companies/{env['a']}/knowledge", headers=ADMIN, json={"title": "Старое", "content": "v1"})
    doc_id = r.json()["id"]
    r = await client.put(f"/api/admin/knowledge/{doc_id}", headers=ADMIN, json={"title": "Новое", "content": "v2"})
    assert r.status_code == 200
    docs = (await client.get(f"/api/admin/companies/{env['a']}/knowledge", headers=ADMIN)).json()
    assert docs[0]["title"] == "Новое" and docs[0]["content"] == "v2" and docs[0]["updated_at"]
    assert (await client.put(f"/api/admin/knowledge/{doc_id}", headers=as_user(101), json={"title": "x", "content": "y"})).status_code == 403


async def test_daily_post_limit_blocks_new_posts(client, env):
    await client.put(f"/api/admin/companies/{env['a']}", headers=ADMIN, json={"daily_post_limit": 1})
    first = (await client.post("/api/agent/message", headers=as_user(100), json={"text": "Напиши пост 1"})).json()
    second = (await client.post("/api/agent/message", headers=as_user(100), json={"text": "Напиши пост 2"})).json()
    assert first["post_id"] and second["post_id"] is None
    assert "лимит" in second["reply"].lower()


async def test_token_budget_blocks_agent(client, env):
    await client.put(f"/api/admin/companies/{env['a']}", headers=ADMIN, json={"monthly_token_limit": 100})
    async with SessionLocal() as s:
        s.add(UsageCost(company_id=env["a"], kind="llm", tokens=500))
        await s.commit()
    r = (await client.post("/api/agent/message", headers=as_user(100), json={"text": "Напиши пост"})).json()
    assert r["post_id"] is None and "бюджет" in r["reply"].lower()
    async with SessionLocal() as s:
        assert (await s.execute(select(Post))).scalars().all() == []  # ни поста, ни вызова модели


async def test_revise_blocked_when_budget_exhausted(client, env):
    r = (await client.post("/api/agent/message", headers=as_user(100), json={"text": "Напиши пост"})).json()
    post_id = r["post_id"]
    await client.put(f"/api/admin/companies/{env['a']}", headers=ADMIN, json={"monthly_token_limit": 100})
    async with SessionLocal() as s:
        s.add(UsageCost(company_id=env["a"], kind="llm", tokens=500))
        await s.commit()
    resp = await client.post(f"/api/posts/{post_id}/decision", headers=as_user(100), json={"decision": "revise", "comment": "короче"})
    assert resp.status_code == 429 and "бюджет" in resp.json()["detail"].lower()
    # пост не застрял в «на доработке»
    assert (await client.get(f"/api/posts/{post_id}", headers=as_user(100))).json()["status"] == "pending_approval"


async def test_cost_is_computed_from_tariff(env, monkeypatch):
    from app import agent
    from app.config import settings
    from app.llm.base import LLMResult

    monkeypatch.setattr(settings, "llm_price_input_per_m", 0.30)
    monkeypatch.setattr(settings, "llm_price_output_per_m", 2.00)
    res = LLMResult(text="x", tokens=1_500_000, prompt_tokens=1_000_000, completion_tokens=500_000)
    assert abs(agent.llm_cost_usd(res) - (0.30 + 1.00)) < 1e-9  # 1М входа по 0.30 + 0.5М выхода по 2.00
    async with SessionLocal() as s:
        await agent._record_llm(s, env["a"], res)
        row = (await s.execute(select(UsageCost).where(UsageCost.company_id == env["a"]))).scalars().one()
    assert row.tokens == 1_500_000 and abs(row.cost_usd - 1.30) < 1e-9
    assert agent.llm_cost_usd(LLMResult(text="x", cost_usd=0.5)) == 0.5  # цена от провайдера приоритетнее


async def test_stats_report_budget_and_cost(client, env):
    stats = {s["id"]: s for s in (await client.get("/api/admin/stats", headers=ADMIN)).json()}
    assert {"cost_usd", "month_tokens", "monthly_token_limit"} <= set(stats[env["a"]])


async def test_post_gets_branded_image(client, env):
    r = (await client.post("/api/agent/message", headers=as_user(100), json={"text": "Напиши пост"})).json()
    post = (await client.get(f"/api/posts/{r['post_id']}", headers=as_user(100))).json()
    assert post["image_url"].startswith("/media/cards/")


async def test_asset_upload_validation(client, env):
    url = f"/api/admin/companies/{env['a']}/assets"
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (25, 108, 127, 255)).save(buf, "PNG")
    ok = await client.post(url, headers=ADMIN, data={"kind": "logo_color"}, files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert ok.status_code == 200
    bad_ext = await client.post(url, headers=ADMIN, data={"kind": "logo_color"}, files={"file": ("logo.exe", b"MZ", "application/octet-stream")})
    fake_img = await client.post(url, headers=ADMIN, data={"kind": "logo_color"}, files={"file": ("logo.png", b"not an image", "image/png")})
    bad_kind = await client.post(url, headers=ADMIN, data={"kind": "script"}, files={"file": ("a.png", buf.getvalue(), "image/png")})
    forbidden = await client.post(url, headers=as_user(101), data={"kind": "logo_color"}, files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert (bad_ext.status_code, fake_img.status_code, bad_kind.status_code, forbidden.status_code) == (422, 422, 422, 403)


async def test_logo_color_follows_background(env):
    """Брендбук: на светлом фоне — цветной логотип, на тёмном — белый."""
    from app.media import new_media_file
    from app.models import BrandAsset

    async with SessionLocal() as s:
        company = await s.get(Company, env["a"])
        # синтетические логотипы: бренд-пакет клиента в репозитории не хранится
        for kind, rgb in (("logo_color", (25, 108, 127)), ("logo_white", (255, 255, 255))):
            dst, url = new_media_file(f"brand/{company.id}", ".png")
            Image.new("RGBA", (400, 160), rgb + (255,)).save(dst, "PNG")
            s.add(BrandAsset(company_id=company.id, kind=kind, filename=f"{kind}.png", path=url))
        await s.commit()
        brand = await branding.load_brand(s, company)
    light = branding.place_logo(Image.new("RGB", (800, 800), (240, 240, 240)), brand)
    dark = branding.place_logo(Image.new("RGB", (800, 800), (20, 40, 50)), brand)
    # на светлом фоне в области логотипа появились тёмные пиксели, на тёмном — светлые
    assert min(light.convert("L").crop((0, 600, 300, 800)).getdata()) < 150
    assert max(dark.convert("L").crop((0, 600, 300, 800)).getdata()) > 200
