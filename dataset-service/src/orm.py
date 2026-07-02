from sqlalchemy import Column, Integer, String, Boolean, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class DatasetORM(Base):
    __tablename__ = "datasets"

    name = Column(String(254), primary_key=True, nullable=False)
    requirements = Column(JSON, nullable=False, default=dict)  # beta(d)
    size_mb = Column(Integer, nullable=False, default=0)
    nodes = Column(JSON, nullable=False, default=list)  # lambda(d)
    geo = Column(String(254), nullable=True, default=None)  # geo(d); None = Omega
    static = Column(Boolean, nullable=False, default=False)  # d in D_static
