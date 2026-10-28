import tempfile
from pathlib import Path

from src.api.utils.notebook_manager import NotebookManager


def test_notebook_manager_supports_chat_record_type_in_statistics():
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = NotebookManager(base_dir=tmp_dir)
        notebook = manager.create_notebook(name="Test Notebook")

        manager.add_record(
            notebook_ids=[notebook["id"]],
            record_type="chat",
            title="Chat note",
            user_query="Hello",
            output="World",
            metadata={"source": "test"},
        )

        stats = manager.get_statistics()
        assert stats["total_notebooks"] == 1
        assert stats["total_records"] == 1
        assert stats["records_by_type"]["chat"] == 1


def test_notebook_manager_add_and_remove_record_updates_index_count():
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = NotebookManager(base_dir=tmp_dir)
        notebook = manager.create_notebook(name="Record Ops")

        result = manager.add_record(
            notebook_ids=[notebook["id"]],
            record_type="solve",
            title="Solve",
            user_query="2+2",
            output="4",
        )
        record_id = result["record"]["id"]

        listed = manager.list_notebooks()
        assert listed[0]["record_count"] == 1

        removed = manager.remove_record(notebook["id"], record_id)
        assert removed is True

        listed_after = manager.list_notebooks()
        assert listed_after[0]["record_count"] == 0


def test_notebook_manager_supports_canvas_and_slide_pro_types():
    with tempfile.TemporaryDirectory() as tmp_dir:
        manager = NotebookManager(base_dir=tmp_dir)
        notebook = manager.create_notebook(name="Extended Types")

        manager.add_record(
            notebook_ids=[notebook["id"]],
            record_type="canvas",
            title="Canvas Record",
            user_query="Canvas query",
            output="Canvas output",
        )
        manager.add_record(
            notebook_ids=[notebook["id"]],
            record_type="slide_pro",
            title="Slide Record",
            user_query="Slide query",
            output="Slide output",
        )

        stats = manager.get_statistics()
        assert stats["total_records"] == 2
        assert stats["records_by_type"]["canvas"] == 1
        assert stats["records_by_type"]["slide_pro"] == 1
