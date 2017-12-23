import os
import bpy
import sys
import inspect
import pkgutil
import importlib

base_classes_to_register = (
    bpy.types.Panel,
    bpy.types.Menu,
    bpy.types.Node,
    bpy.types.NodeTree,
    bpy.types.NodeSocket,
    bpy.types.Operator
)

def setup_addon_modules(path, package_name, reload):
    """
    Imports and reloads all modules in this addon.

    path -- __path__ from __init__.py
    package_name -- __name__ from __init__.py

    Individual modules can define a __reload_order_index__ property which
    will be used to reload the modules in a specific order. The default is 0.
    """
    def iter_submodule_names(path = path[0], root = ""):
        for importer, module_name, is_package in pkgutil.iter_modules([path]):
            if is_package:
                sub_path = os.path.join(path, module_name)
                sub_root = root + module_name + "."
                yield from get_submodule_names(sub_path, sub_root)
            else:
                yield root + module_name

    def import_submodules(names):
        for name in names:
            yield importlib.import_module("." + name, package_name)

    def reload_modules(modules):
        modules.sort(key = lambda module: getattr(module, "__reload_order_index__", 0))
        for module in modules:
            importlib.reload(module)

    def iter_classes_to_register(modules):
        for module in modules:
            for attribute in dir(module):
                value = getattr(module, attribute)
                if inspect.isclass(value):
                    if issubclass(value, base_classes_to_register):
                        yield value

    names = list(iter_submodule_names())
    modules = list(import_submodules(names))
    if reload:
        reload_modules(modules)

    classes = list(iter_classes_to_register(modules))

    return modules, classes
