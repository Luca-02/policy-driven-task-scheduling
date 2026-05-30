from functools import lru_cache

from fastapi import Depends

from src.config import Config
from src.database import DatasetRepository


@lru_cache
def get_config() -> Config:
    return Config.from_env()


@lru_cache
def get_repository(cfg: Config = Depends(get_config)) -> DatasetRepository:
    return DatasetRepository(cfg.db_path)
