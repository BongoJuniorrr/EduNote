"""
About manager - Stores team member information for the About Us page.
Data is persisted under data/user/about/members.json.
"""

import json
from pathlib import Path
import time
import uuid


ALLOWED_MEMBER_ROLES = ["Tech Lead", "Dev", "Tester", "Reporter"]


class AboutManager:
    """Manage About Us members with simple JSON persistence."""

    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            project_root = Path(__file__).resolve().parents[3]
            base_dir_path = project_root / "data" / "user" / "about"
        else:
            base_dir_path = Path(base_dir)

        self.base_dir = base_dir_path
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.members_file = self.base_dir / "members.json"
        self._ensure_file()

    def _ensure_file(self):
        if not self.members_file.exists():
            with open(self.members_file, "w", encoding="utf-8") as f:
                json.dump({"members": []}, f, indent=2, ensure_ascii=False)

    def _load(self) -> dict:
        try:
            with open(self.members_file, encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"members": []}
                members = data.get("members", [])
                if not isinstance(members, list):
                    return {"members": []}
                return {"members": members}
        except Exception:
            return {"members": []}

    def _save(self, data: dict):
        with open(self.members_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_members(self) -> list[dict]:
        data = self._load()
        members = data.get("members", [])
        members.sort(key=lambda item: item.get("created_at", 0), reverse=True)
        return members

    def add_member(
        self,
        full_name: str,
        alias: str,
        student_id: str,
        university: str,
        roles: list[str],
        tasks: str,
    ) -> dict:
        now = time.time()
        normalized_roles = []
        seen = set()
        for role in roles:
            role_clean = str(role).strip()
            if role_clean in ALLOWED_MEMBER_ROLES and role_clean not in seen:
                seen.add(role_clean)
                normalized_roles.append(role_clean)

        member = {
            "id": str(uuid.uuid4())[:8],
            "full_name": full_name.strip(),
            "alias": alias.strip(),
            "student_id": student_id.strip(),
            "university": university.strip(),
            "roles": normalized_roles,
            "tasks": tasks.strip(),
            "created_at": now,
            "updated_at": now,
        }

        data = self._load()
        members = data.get("members", [])
        members.append(member)
        data["members"] = members
        self._save(data)
        return member

    def delete_member(self, member_id: str) -> bool:
        data = self._load()
        members = data.get("members", [])
        new_members = [member for member in members if member.get("id") != member_id]
        if len(new_members) == len(members):
            return False
        data["members"] = new_members
        self._save(data)
        return True


about_manager = AboutManager()

