import json
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from .database import Base


class PipelineModel(Base):
    __tablename__ = "pipelines"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="Untitled Pipeline")
    description = Column(Text, default="")
    nodes_json = Column(Text, default="[]")
    edges_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def nodes(self):
        return json.loads(self.nodes_json) if self.nodes_json else []

    @nodes.setter
    def nodes(self, value):
        self.nodes_json = json.dumps(value)

    @property
    def edges(self):
        return json.loads(self.edges_json) if self.edges_json else []

    @edges.setter
    def edges(self, value):
        self.edges_json = json.dumps(value)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": self.nodes,
            "edges": self.edges,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FileModel(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    rows = Column(String, default="0")
    columns_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def columns_list(self):
        return json.loads(self.columns_json) if self.columns_json else []

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "rows": int(self.rows),
            "columns": self.columns_list,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
