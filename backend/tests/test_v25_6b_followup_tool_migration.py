"""The V25.6b migration renames persisted agent actions to the new tool name and is idempotent."""

from pathlib import Path

from sqlalchemy import create_engine, text

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "v25_6b_rename_followup_tool.sql"


def _statements() -> list[str]:
    lines = [ln for ln in MIGRATION.read_text().splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def test_migration_renames_old_tool_rows_and_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE career_agent_actions (id INTEGER PRIMARY KEY, action_type VARCHAR(60), status VARCHAR(30))"))
        conn.execute(text(
            "INSERT INTO career_agent_actions (action_type, status) VALUES "
            "('send_recruiter_message', 'PENDING_CONFIRMATION'), ('send_recruiter_message', 'COMPLETED'), "
            "('schedule_follow_up', 'PENDING_CONFIRMATION')"
        ))
        for _ in range(2):  # second pass proves re-running is harmless
            for stmt in _statements():
                conn.execute(text(stmt))
        rows = conn.execute(text("SELECT action_type, COUNT(*) FROM career_agent_actions GROUP BY action_type ORDER BY 1")).all()
    assert rows == [("draft_followup_message", 2), ("schedule_follow_up", 1)]


def test_new_tool_name_is_registered_and_old_one_is_gone():
    from app.career_agent import permissions, tool_registry

    assert "draft_followup_message" in tool_registry.TOOLS
    assert "send_recruiter_message" not in tool_registry.TOOLS
    permissions.assert_candidate_safe_tool_name("draft_followup_message")
