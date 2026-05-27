"""Auto-discover and register all node types."""
from ..nodes.base import BaseNode, NodeDefinition
from ..nodes.input_csv import InputCSVNode
from ..nodes.input_xlsx import InputXLSXNode
from ..nodes.input_json import InputJSONNode
from ..nodes.input_api import InputAPINode
from ..nodes.transform_normalize import TransformNormalizeNode, register_function
from ..nodes.transform_filter import TransformFilterNode
from ..nodes.transform_split import TransformSplitNode
from ..nodes.transform_merge import TransformMergeNode
from ..nodes.transform_formula import TransformFormulaNode
from ..nodes.transform_group import TransformGroupNode
from ..nodes.transform_deduplicate import TransformDeduplicateNode
from ..nodes.transform_pivot import TransformPivotNode
from ..nodes.transform_sample import TransformSampleNode
from ..nodes.ai_enrich import AIEnrichNode
from ..nodes.ai_classify import AIClassifyNode
from ..nodes.ai_search import AISearchNode
from ..nodes.ai_autofill import AIAutoFillNode
from ..nodes.ai_vision import AIVisionNode
from ..nodes.ai_cross_match import AICrossMatchNode
from ..nodes.ai_map_analysis import AIMapAnalysisNode
from ..nodes.input_images import InputImagesNode
from ..nodes.lookup_dictionary import LookupDictionaryNode, register_builtin
from ..nodes.output_xlsx import OutputXLSXNode
from ..nodes.output_json import OutputJSONNode
from ..nodes.output_csv import OutputCSVNode

_REGISTRY: dict[str, type[BaseNode]] = {}


def _register(cls: type[BaseNode]):
    defn = cls.definition()
    _REGISTRY[defn.type] = cls


def init_registry():
    # Core input nodes
    _register(InputCSVNode)
    _register(InputXLSXNode)
    _register(InputJSONNode)
    _register(InputAPINode)
    _register(InputImagesNode)

    # Core transform nodes
    _register(TransformNormalizeNode)
    _register(TransformFilterNode)
    _register(TransformSplitNode)
    _register(TransformMergeNode)
    _register(TransformFormulaNode)
    _register(TransformGroupNode)
    _register(TransformDeduplicateNode)
    _register(TransformPivotNode)
    _register(TransformSampleNode)

    # AI nodes
    _register(AIEnrichNode)
    _register(AIClassifyNode)
    _register(AISearchNode)
    _register(AIAutoFillNode)
    _register(AIVisionNode)
    _register(AICrossMatchNode)
    _register(AIMapAnalysisNode)

    # Lookup nodes
    _register(LookupDictionaryNode)

    # Core output nodes
    _register(OutputXLSXNode)
    _register(OutputJSONNode)
    _register(OutputCSVNode)

    # Discover and load plugins
    from ..plugins import discover_plugins
    discover_plugins(
        node_registry_fn=_register,
        normalize_registry_fn=register_function,
        dictionary_registry_fn=register_builtin,
    )


def get_node_class(node_type: str) -> type[BaseNode]:
    if node_type not in _REGISTRY:
        raise ValueError(f"Unknown node type: {node_type}")
    return _REGISTRY[node_type]


def get_all_definitions() -> list[NodeDefinition]:
    return [cls.definition() for cls in _REGISTRY.values()]


def get_all_types() -> list[str]:
    return list(_REGISTRY.keys())
