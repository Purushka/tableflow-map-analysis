"""Plugin auto-discovery system."""
import importlib
import os
import sys


def discover_plugins(node_registry_fn, normalize_registry_fn, dictionary_registry_fn):
    """Scan backend/plugins/ for sub-packages containing plugin.py with register()."""
    plugins_dir = os.path.dirname(__file__)

    for entry in os.listdir(plugins_dir):
        plugin_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(plugin_path):
            continue
        if entry.startswith("_"):
            continue

        plugin_module_path = os.path.join(plugin_path, "plugin.py")
        if not os.path.exists(plugin_module_path):
            continue

        try:
            module = importlib.import_module(f".{entry}.plugin", package="backend.plugins")
            if hasattr(module, "register"):
                module.register(node_registry_fn, normalize_registry_fn, dictionary_registry_fn)
                print(f"[plugin] Loaded: {entry}")
            else:
                print(f"[plugin] {entry}/plugin.py has no register() function, skipping")
        except Exception as e:
            print(f"[plugin] Failed to load {entry}: {e}")
