"""RGSSA Plugin — Boggs-Lewis area matching, LCSH generation, and domain-specific normalize functions."""

PLUGIN_META = {
    "id": "rgssa",
    "label": "RGSSA Map Cataloguing",
    "description": "Boggs-Lewis classification, LCSH subject headings, and map-specific normalization",
}


def register(node_registry_fn, normalize_registry_fn, dictionary_registry_fn):
    """Called by the plugin discovery system."""
    # Register nodes
    from .lookup_bl_area import LookupBLAreaNode
    from .lookup_lcsh import LookupLCSHNode
    node_registry_fn(LookupBLAreaNode)
    node_registry_fn(LookupLCSHNode)

    # Register normalize functions
    from .normalize_functions import FUNCTIONS
    for name, fn in FUNCTIONS.items():
        normalize_registry_fn(name, fn)

    # Register builtin dictionaries
    from .data.boggs_lewis import AREA_CODES, SUBJECT_CODES
    from .data.tiered_rag import PLACE_TO_BL_AREA, THEME_TO_BL_SUBJECT
    dictionary_registry_fn("bl_area_codes", AREA_CODES)
    dictionary_registry_fn("bl_subject_codes", SUBJECT_CODES)
    dictionary_registry_fn("place_to_bl_area", PLACE_TO_BL_AREA)
    dictionary_registry_fn("theme_to_bl_subject", THEME_TO_BL_SUBJECT)
