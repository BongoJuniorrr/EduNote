"""
Notebook Manager - Manages user notebooks and records
All notebook data is stored in user/notebook/ directory
"""

from enum import Enum
import json
from pathlib import Path
import time
import uuid

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    """Record type"""

    SOLVE = "solve"
    QUESTION = "question"
    RESEARCH = "research"
    CO_WRITER = "co_writer"
    CHAT = "chat"
    NOTE = "note"
    CANVAS = "canvas"
    SLIDE_PRO = "slide_pro"


class NotebookRecord(BaseModel):
    """Single record in notebook"""

    id: str
    type: RecordType
    title: str
    user_query: str
    output: str
    metadata: dict = Field(default_factory=dict)
    created_at: float
    kb_name: str | None = None


class Notebook(BaseModel):
    """Notebook model"""

    id: str
    name: str
    description: str = ""
    created_at: float
    updated_at: float
    records: list[NotebookRecord] = Field(default_factory=list)
    color: str = "#3B82F6"  # Default blue
    icon: str = "book"  # Default icon


class NotebookManager:
    """Notebook manager"""

    def __init__(self, base_dir: str | None = None):
        """
        Initialize notebook manager

        Args:
            base_dir: Notebook storage directory, defaults to project root/user/notebook
        """
        if base_dir is None:
            # Current file: EduNote/src/api/utils/notebook_manager.py
            # Project root should be three levels up: EduNote/
            project_root = Path(__file__).resolve().parents[3]
            base_dir_path = project_root / "data" / "user" / "notebook"
        else:
            base_dir_path = Path(base_dir)

        self.base_dir = base_dir_path
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Notebook index file
        self.index_file = self.base_dir / "notebooks_index.json"
        self._ensure_index()

    def _ensure_index(self):
        """Ensure index file exists"""
        if not self.index_file.exists():
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({"notebooks": []}, f, indent=2, ensure_ascii=False)

    def _load_index(self) -> dict:
        """Load index"""
        try:
            with open(self.index_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"notebooks": []}

    def _save_index(self, index: dict):
        """Save index"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _get_notebook_file(self, notebook_id: str) -> Path:
        """Get notebook file path"""
        return self.base_dir / f"{notebook_id}.json"

    def _load_notebook(self, notebook_id: str) -> dict | None:
        """Load single notebook"""
        filepath = self._get_notebook_file(notebook_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_notebook(self, notebook: dict):
        """Save single notebook"""
        filepath = self._get_notebook_file(notebook["id"])
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(notebook, f, indent=2, ensure_ascii=False)

    # === Notebook Operations ===

    def create_notebook(
        self, name: str, description: str = "", color: str = "#3B82F6", icon: str = "book"
    ) -> dict:
        """
        Create new notebook

        Args:
            name: Notebook name
            description: Notebook description
            color: Color code
            icon: Icon name

        Returns:
            Created notebook information
        """
        notebook_id = str(uuid.uuid4())[:8]
        now = time.time()

        notebook = {
            "id": notebook_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "records": [],
            "color": color,
            "icon": icon,
        }

        # Save notebook file
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        index["notebooks"].append(
            {
                "id": notebook_id,
                "name": name,
                "description": description,
                "created_at": now,
                "updated_at": now,
                "record_count": 0,
                "color": color,
                "icon": icon,
            }
        )
        self._save_index(index)

        return notebook

    def list_notebooks(self) -> list[dict]:
        """
        List all notebooks (summary information)

        Returns:
            Notebook list
        """
        index = self._load_index()
        notebooks = []

        for nb_info in index.get("notebooks", []):
            # Get latest information from actual file
            notebook = self._load_notebook(nb_info["id"])
            if notebook:
                notebooks.append(
                    {
                        "id": notebook["id"],
                        "name": notebook["name"],
                        "description": notebook.get("description", ""),
                        "created_at": notebook["created_at"],
                        "updated_at": notebook["updated_at"],
                        "record_count": len(notebook.get("records", [])),
                        "color": notebook.get("color", "#3B82F6"),
                        "icon": notebook.get("icon", "book"),
                    }
                )

        # Sort by update time
        notebooks.sort(key=lambda x: x["updated_at"], reverse=True)
        return notebooks

    def get_notebook(self, notebook_id: str) -> dict | None:
        """
        Get notebook details (includes all records)

        Args:
            notebook_id: Notebook ID

        Returns:
            Notebook details
        """
        return self._load_notebook(notebook_id)

    def update_notebook(
        self,
        notebook_id: str,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        icon: str | None = None,
    ) -> dict | None:
        """
        Update notebook information

        Args:
            notebook_id: Notebook ID
            name: New name
            description: New description
            color: New color
            icon: New icon

        Returns:
            Updated notebook information
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return None

        if name is not None:
            notebook["name"] = name
        if description is not None:
            notebook["description"] = description
        if color is not None:
            notebook["color"] = color
        if icon is not None:
            notebook["icon"] = icon

        notebook["updated_at"] = time.time()
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        for nb_info in index["notebooks"]:
            if nb_info["id"] == notebook_id:
                if name is not None:
                    nb_info["name"] = name
                if description is not None:
                    nb_info["description"] = description
                if color is not None:
                    nb_info["color"] = color
                if icon is not None:
                    nb_info["icon"] = icon
                nb_info["updated_at"] = notebook["updated_at"]
                break
        self._save_index(index)

        return notebook

    def delete_notebook(self, notebook_id: str) -> bool:
        """
        Delete notebook

        Args:
            notebook_id: Notebook ID

        Returns:
            Whether deletion was successful
        """
        filepath = self._get_notebook_file(notebook_id)
        if not filepath.exists():
            return False

        # Delete file
        filepath.unlink()

        # Update index
        index = self._load_index()
        index["notebooks"] = [nb for nb in index["notebooks"] if nb["id"] != notebook_id]
        self._save_index(index)

        return True

    # === Record Operations ===

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: RecordType,
        title: str,
        user_query: str,
        output: str,
        metadata: dict = None,
        kb_name: str = None,
    ) -> dict:
        """
        Add record to one or more notebooks

        Args:
            notebook_ids: Target notebook ID list
            record_type: Record type
            title: Title
            user_query: User input
            output: Output result
            metadata: Additional metadata
            kb_name: Knowledge base name

        Returns:
            Added record information
        """
        record_id = str(uuid.uuid4())[:8]
        now = time.time()

        record = {
            "id": record_id,
            "type": record_type,
            "title": title,
            "user_query": user_query,
            "output": output,
            "metadata": metadata or {},
            "created_at": now,
            "kb_name": kb_name,
        }

        added_to = []
        for notebook_id in notebook_ids:
            notebook = self._load_notebook(notebook_id)
            if notebook:
                notebook["records"].append(record)
                notebook["updated_at"] = now
                self._save_notebook(notebook)
                added_to.append(notebook_id)

                # Update update time and record count in index
                index = self._load_index()
                for nb_info in index["notebooks"]:
                    if nb_info["id"] == notebook_id:
                        nb_info["updated_at"] = now
                        nb_info["record_count"] = len(notebook["records"])
                        break
                self._save_index(index)

        return {"record": record, "added_to_notebooks": added_to}

    @staticmethod
    def _is_manual_note(record: dict) -> bool:
        """Check whether a record is a user-created manual note."""
        if record.get("type") != RecordType.NOTE.value:
            return False

        metadata = record.get("metadata") or {}
        source = str(metadata.get("source", "")).strip().lower()
        # Support legacy notes (empty source) and explicit manual notes.
        return source == "" or source.startswith("manual_note")

    def update_manual_note(
        self,
        notebook_id: str,
        record_id: str,
        title: str,
        content: str,
    ) -> tuple[dict | None, str]:
        """
        Update a manual note record.

        Returns:
            (record, reason)
            - reason="ok" on success
            - reason in {"notebook_not_found", "record_not_found", "forbidden"}
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return None, "notebook_not_found"

        now = time.time()
        for record in notebook.get("records", []):
            if record.get("id") != record_id:
                continue
            if not self._is_manual_note(record):
                return None, "forbidden"

            normalized_title = title.strip()
            normalized_content = content.strip()
            preview = (
                f"{normalized_content[:240]}..."
                if len(normalized_content) > 240
                else normalized_content
            )

            record["title"] = normalized_title
            record["output"] = normalized_content
            record["user_query"] = preview

            metadata = record.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                record["metadata"] = metadata
            metadata["source"] = "manual_note"
            metadata["updated_at"] = now

            notebook["updated_at"] = now
            self._save_notebook(notebook)

            index = self._load_index()
            for nb_info in index["notebooks"]:
                if nb_info["id"] == notebook_id:
                    nb_info["updated_at"] = now
                    nb_info["record_count"] = len(notebook.get("records", []))
                    break
            self._save_index(index)

            return record, "ok"

        return None, "record_not_found"

    def remove_manual_note(self, notebook_id: str, record_id: str) -> tuple[bool, str]:
        """
        Remove a manual note record.

        Returns:
            (success, reason)
            - reason="ok" on success
            - reason in {"notebook_not_found", "record_not_found", "forbidden"}
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return False, "notebook_not_found"

        target_record = None
        for record in notebook.get("records", []):
            if record.get("id") == record_id:
                target_record = record
                break

        if not target_record:
            return False, "record_not_found"
        if not self._is_manual_note(target_record):
            return False, "forbidden"

        notebook["records"] = [r for r in notebook.get("records", []) if r.get("id") != record_id]
        notebook["updated_at"] = time.time()
        self._save_notebook(notebook)

        index = self._load_index()
        for nb_info in index["notebooks"]:
            if nb_info["id"] == notebook_id:
                nb_info["updated_at"] = notebook["updated_at"]
                nb_info["record_count"] = len(notebook.get("records", []))
                break
        self._save_index(index)

        return True, "ok"

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        """
        Remove record from notebook

        Args:
            notebook_id: Notebook ID
            record_id: Record ID

        Returns:
            Whether deletion was successful
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return False

        original_count = len(notebook["records"])
        notebook["records"] = [r for r in notebook["records"] if r["id"] != record_id]

        if len(notebook["records"]) == original_count:
            return False

        notebook["updated_at"] = time.time()
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        for nb_info in index["notebooks"]:
            if nb_info["id"] == notebook_id:
                nb_info["updated_at"] = notebook["updated_at"]
                nb_info["record_count"] = len(notebook["records"])
                break
        self._save_index(index)

        return True

    def get_statistics(self) -> dict:
        """
        Get notebook statistics

        Returns:
            Statistics information
        """
        notebooks = self.list_notebooks()

        total_records = 0
        type_counts = {
            "solve": 0,
            "question": 0,
            "research": 0,
            "co_writer": 0,
            "chat": 0,
            "note": 0,
            "canvas": 0,
            "slide_pro": 0,
        }

        for nb_info in notebooks:
            notebook = self._load_notebook(nb_info["id"])
            if notebook:
                for record in notebook.get("records", []):
                    total_records += 1
                    record_type = record.get("type", "")
                    if record_type in type_counts:
                        type_counts[record_type] += 1

        return {
            "total_notebooks": len(notebooks),
            "total_records": total_records,
            "records_by_type": type_counts,
            "recent_notebooks": notebooks[:5],
        }


# Global instance
notebook_manager = NotebookManager()
