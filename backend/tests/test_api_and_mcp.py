import pytest
from fastapi.testclient import TestClient
from app.database.database import init_db
from app.main import app
from app.mcp.server import mcp

init_db()
AUTH_HEADER = {"Authorization": "Bearer dev-token:tejasvi_test"}


def test_health_and_auth_guard():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

        # Unauthenticated request must be rejected with 401
        unauth = client.get("/runs")
        assert unauth.status_code == 401


def test_vault_and_runs_endpoints():
    with TestClient(app) as client:
        create_res = client.post(
            "/vault/credentials",
            headers=AUTH_HEADER,
            json={
                "label": "demo_site",
                "domain": "example.com",
                "username": "tejasvi",
                "password": "MyPassword123",
            },
        )
        assert create_res.status_code == 200

        # List credentials must return placeholder, never raw password
        list_res = client.get("/vault/credentials", headers=AUTH_HEADER)
        assert list_res.status_code == 200
        body = str(list_res.json())
        assert "{{VAULT:demo_site}}" in body
        assert "MyPassword123" not in body


@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert {"run_web_task", "extract_page_data", "replay_workflow"}.issubset(tool_names)