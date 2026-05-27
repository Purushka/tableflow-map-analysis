from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING
from pydantic import BaseModel
import pandas as pd

if TYPE_CHECKING:
    from ..engine.context import PipelineContext


class PortDefinition(BaseModel):
    name: str
    label: str
    type: str = "dataframe"
    multiple: bool = False


class ConfigField(BaseModel):
    name: str
    label: str
    type: str  # text | number | boolean | select | column_select | file | prompt_template | json
    required: bool = False
    default: Any = None
    options: list = []
    description: str = ""
    placeholder: str = ""
    accept: str = ""  # File input accept filter, e.g. ".zip" or ".csv,.xlsx"


class NodeDefinition(BaseModel):
    type: str
    label: str
    category: str  # input | transform | ai | lookup | output
    icon: str
    color: str
    description: str
    inputs: list[PortDefinition]
    outputs: list[PortDefinition]
    config_fields: list[ConfigField]
    plugin: str = ""  # Empty for core nodes, "rgssa" etc. for plugin nodes


class BaseNode(ABC):
    @classmethod
    @abstractmethod
    def definition(cls) -> NodeDefinition:
        ...

    @abstractmethod
    async def execute(
        self,
        inputs: dict[str, pd.DataFrame],
        config: dict,
        on_progress=None,
        context: "PipelineContext | None" = None,
    ) -> dict[str, pd.DataFrame]:
        ...
