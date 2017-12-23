from llvmlite import ir
import llvmlite.binding as llvm
from . utils.timing import measureTime
from . utils.nodes import iter_compute_nodes_in_tree, iter_compute_node_trees
from . tree_info import get_direct_dependency_node_names, iter_unlinked_inputs, iter_linked_inputs, get_data_origin_socket
from pprint import pprint


class TreeExecutionData:
    def __init__(self, tree):
        self.tree_hash = hash(tree)

        llvm_target = llvm.Target.from_default_triple()
        llvm_target_machine = llvm_target.create_target_machine()
        empty_module = llvm.parse_assembly("")
        self.engine = llvm.create_mcjit_compiler(empty_module, llvm_target_machine)

        self.globals_module_ir = self._create_globals_module(tree)
        self.globals_module = self._compile_ir_module(self.globals_module_ir)
        self.compute_modules = dict()

    def _compile_ir_module(self, ir_module):
        module = llvm.parse_assembly(str(ir_module))
        module.name = ir_module.name
        module.verify()
        self.engine.add_module(module)
        self.engine.finalize_object()
        return module

    def _create_globals_module(self, tree):
        module = ir.Module("Globals")
        for node, socket in iter_all_unlinked_inputs(tree):
            name = get_global_input_name(node, socket)
            variable = ir.GlobalVariable(module, socket.ir_type, name)
            variable.linkage = "internal"
        return module

    def get_compute_module(self, output_socket):
        socket_hash = hash(output_socket)
        if socket_hash not in self.compute_modules:
            module_ir = self._create_compute_module(output_socket)
            module = self._compile_ir_module(module_ir)
            self.compute_modules[socket_hash] = module

        return self.compute_modules[socket_hash]

    def _create_compute_module(self, output_socket):
        tree = self.get_tree()
        if output_socket.id_data != tree:
            raise Exception("output socket is in wrong tree")

        module_name = "ID1".format(output_socket.node.name, output_socket.identifier)

        module = ir.Module(module_name)
        self.node_functions = {}
        for node in iter_compute_nodes_in_tree(tree):
            f = create_node_function(module, node)
            self.node_functions[node.name] = f

        main_type = ir.FunctionType(output_socket.ir_type, tuple())
        main_function = ir.Function(module, main_type, name = "Main " + output_socket.node.name + " " + output_socket.identifier)

        create_main_code(main_function, self.globals_module_ir, tree, output_socket, self.node_functions)
        print(module)
        return module

    def get_tree(self):
        for tree in iter_compute_node_trees():
            if hash(tree) == self.tree_hash:
                return tree
        raise Exception("cannot find tree")

    def update_globals(self):
        tree = self.get_tree()
        for node, socket in iter_all_unlinked_inputs(tree):
            name = get_global_input_name(node, socket)
            address = self.engine.get_global_value_address(name)
            socket.update_at_address(address)

def iter_all_unlinked_inputs(tree):
    for node in iter_compute_nodes_in_tree(tree):
        for socket in iter_unlinked_inputs(node):
            yield node, socket

def create_node_function(module, node):
    input_types = list(iter_input_socket_types(node))
    output_types = list(iter_output_socket_pointer_types(node))

    function_type = ir.FunctionType(ir.VoidType(), input_types + output_types)
    function = ir.Function(module, function_type, name = node.name)

    input_args = function.args[:len(input_types)]
    output_args = function.args[len(input_types):]


    block_calc = function.append_basic_block("calculate")
    builder_calc = ir.IRBuilder(block_calc)
    output_variables = node.create_llvm_ir(builder_calc, *input_args)

    block_store = function.append_basic_block("store_output")
    builder_calc.branch(block_store)
    builder_store = ir.IRBuilder(block_store)
    for var, arg in zip(output_variables, output_args):
        builder_store.store(var, arg)
    builder_store.ret_void()

    return function

def iter_input_socket_types(node):
    for socket in node.inputs:
        yield socket.ir_type

def iter_output_socket_pointer_types(node):
    for socket in node.outputs:
        yield socket.ir_type.as_pointer()


def create_main_code(function, globals_module, tree, output_socket, functions):
    node_by_name = dict(tree.nodes)
    nodes = list(iter_dependency_nodes(output_socket.node, node_by_name))
    variables = {}
    block = function.append_basic_block("entry")
    builder = ir.IRBuilder(block)
    create_unlinked_input_variables(builder, nodes, variables)

    for node in nodes:
        for socket in iter_linked_inputs(node):
            origin = get_data_origin_socket(socket)
            variables[socket] = variables[origin]
        input_parameters = [variables[socket] for socket in node.inputs]
        output_parameters = [builder.alloca(socket.ir_type) for socket in node.outputs]
        builder.call(functions[node.name], input_parameters + output_parameters)
        for i, socket in enumerate(node.outputs):
            variables[socket] = builder.load(output_parameters[i])

    builder.ret(variables[output_socket])
    pprint(variables)

def iter_dependency_nodes(node, node_by_name, visited = None):
    if visited is None:
        visited = set()

    for name in get_direct_dependency_node_names(node):
        dependency_node = node_by_name[name]
        if dependency_node not in visited:
            yield from iter_dependency_nodes(dependency_node, node_by_name, visited)

    visited.add(node)
    yield node

def create_unlinked_input_variables(builder, nodes, variables):
    for node in nodes:
        for socket in iter_unlinked_inputs(node):
            name = get_global_input_name(node, socket)
            source_variable = ir.GlobalVariable(builder.block.function.module, socket.ir_type, name)
            source_variable.linkage = "available_externally"
            variable = builder.load(source_variable)
            variables[socket] = variable


def get_global_input_name(node, socket):
    return validify_name(node.name) + " - " + validify_name(socket.identifier)

def validify_name(name):
    return name.replace('"', "")
