from pathlib import Path
import os
import subprocess

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def test_alembic_revisions_are_unique_and_have_single_head():
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    revision_ids = [revision.revision for revision in revisions]

    assert len(revision_ids) == len(set(revision_ids))
    assert len(script.get_heads()) == 1


def test_vision_config_migration_handles_existing_table(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "dirty_vision.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260623_0003')"))
        conn.execute(text(
            "CREATE TABLE vision_model_config ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tenant_id INTEGER NOT NULL DEFAULT 0, "
            "enabled BOOLEAN NOT NULL DEFAULT 1, "
            "protocol VARCHAR(16) NOT NULL DEFAULT 'openai', "
            "base_url VARCHAR(512), "
            "model_name VARCHAR(256), "
            "api_key_cipher VARCHAR(1024), "
            "max_tokens INTEGER NOT NULL DEFAULT 2000, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "CONSTRAINT uq_vision_model_config_tenant UNIQUE (tenant_id)"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_vision_model_config_tenant_id ON vision_model_config (tenant_id)"))
        conn.execute(text("CREATE TABLE mcp_service (id INTEGER PRIMARY KEY, created_by_admin_id INTEGER, is_deleted BOOLEAN, status VARCHAR(32), slug VARCHAR(128), config_json TEXT)"))
        conn.execute(text("CREATE INDEX ix_mcp_service_created_by_admin_id ON mcp_service (created_by_admin_id)"))
        conn.execute(text("CREATE INDEX ix_mcp_service_is_deleted ON mcp_service (is_deleted)"))
        conn.execute(text("CREATE INDEX ix_mcp_service_status ON mcp_service (status)"))
        conn.execute(text("CREATE INDEX ix_mcp_service_slug ON mcp_service (slug)"))
        conn.execute(text("CREATE TABLE mcp_tool (id INTEGER PRIMARY KEY, service_id INTEGER)"))
        conn.execute(text("CREATE INDEX ix_mcp_tool_service_id ON mcp_tool (service_id)"))
        conn.execute(text("CREATE TABLE mcp_call_log (id INTEGER PRIMARY KEY, service_id INTEGER, created_by_admin_id INTEGER)"))
        conn.execute(text("CREATE INDEX ix_mcp_call_log_service_id ON mcp_call_log (service_id)"))
        conn.execute(text("CREATE INDEX ix_mcp_call_log_created_by_admin_id ON mcp_call_log (created_by_admin_id)"))

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
    }
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
