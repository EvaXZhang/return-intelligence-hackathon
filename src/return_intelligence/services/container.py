from __future__ import annotations

from ..config import AppConfig
from ..db.repositories import Repository
from ..db.seed import seed_database
from ..providers import create_provider
from .supervisor import SupervisorService


def build_container(config: AppConfig | None = None):
    config = config or AppConfig.from_env()
    repository = Repository(config.db_path)
    repository.initialize()
    seed_database(config.db_path, config.project_root)
    provider = create_provider(config)
    return SupervisorService(
        repository,
        config.artifact_dir,
        config.demo_season,
        provider=provider,
        upload_root=config.upload_dir,
        clock=config.now,
    )
