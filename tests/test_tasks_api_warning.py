from __future__ import annotations

import importlib
import sys
import warnings


def test_tasks_api_import_emits_no_pydantic_v2_config_deprecation():
    module_name = "edict.backend.app.api.tasks"

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if module_name in sys.modules:
            importlib.reload(sys.modules[module_name])
        else:
            importlib.import_module(module_name)

    deprecations = [
        str(item.message)
        for item in caught
        if "class-based `config` is deprecated" in str(item.message)
    ]
    assert deprecations == []
