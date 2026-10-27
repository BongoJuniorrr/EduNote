"""The personal KB and retrieval configuration use the original global paths."""

from src.api.routers import knowledge
from src.services.config import knowledge_base_config


def test_knowledge_manager_uses_global_workspace(tmp_path, monkeypatch):
    base = tmp_path / "knowledge_bases"
    monkeypatch.setattr(knowledge, "_kb_base_dir", base)
    knowledge.kb_managers.clear()
    assert knowledge.get_kb_base_dir() == base
    assert knowledge.get_kb_manager().base_dir == base
    assert knowledge.get_kb_manager() is knowledge.get_kb_manager()


def test_retrieval_profile_persists_in_global_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings" / "knowledge_base_configs.json"
    monkeypatch.setattr(knowledge_base_config, "DEFAULT_CONFIG_PATH", path)
    service = knowledge_base_config.KnowledgeBaseConfigService
    service._instances.clear()
    first = service.get_instance()
    first.set_kb_config("demo", {"rag_provider": "vgu_course"})
    service._instances.clear()
    assert service.get_instance().get_kb_config("demo")["rag_provider"] == "vgu_course"
    assert path.is_file()
