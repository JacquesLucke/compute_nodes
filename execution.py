from llvmlite import ir
import llvmlite.binding as llvm
from . utils.timing import measureTime
from . utils.nodes import iter_compute_nodes_in_tree, iter_compute_node_trees
from . tree_info import get_direct_dependency_node_names, iter_unlinked_inputs, iter_linked_inputs, get_data_origin_socket
from pprint import pprint


class TreeExecutionData:
    def __init__(self, tree):
        self.tree_hash = hash(tree)

        empty_module = llvm.parse_assembly("")
        llvm_target = llvm.Target.from_default_triple()
        self.target_machine = llvm_target.create_target_machine()
        self.engine = llvm.create_mcjit_compiler(empty_module, self.target_machine)

        self.globals_module_ir = self._create_globals_module(tree)
        self.globals_module = self._compile_ir_module(self.globals_module_ir)
        self.compute_modules = dict()

    def _compile_ir_module(self, ir_module):
        module = llvm.parse_assembly(str(ir_module))
        module.name = ir_module.name
        module.verify()
        self.engine.add_module(module)
        self.engine.finalize_object()

        pmb = llvm.PassManagerBuilder()
        pmb.opt_level = 0
        pm = llvm.ModulePassManager()
        pmb.populate(pm)
        pm.run(module)

        return module

    def _create_globals_module(self, tree):
        module = ir.Module("Globals")
        for node, socket in iter_all_unlinked_inputs(tree):
            name = get_global_input_name(node, socket)
            variable = ir.GlobalVariable(module, socket.ir_type, name)
            variable.linkage = "internal"
        return module

    def get_compute_module(self, output_sockets):
        socket_hash = hash(tuple(output_sockets))
        if socket_hash not in self.compute_modules:
            module_ir = self._create_compute_module(output_sockets)
            module = self._compile_ir_module(module_ir)
            self.compute_modules[socket_hash] = module

        return self.compute_modules[socket_hash]

    def _create_compute_module(self, output_sockets):
        module = generate_compute_module(output_sockets)
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

def iter_input_socket_types(node):
    for socket in node.inputs:
        yield socket.ir_type

def iter_output_socket_pointer_types(node):
    for socket in node.outputs:
        yield socket.ir_type.as_pointer()


def create_main_code(function, globals_module, tree, output_socket):
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
        next_block, *outputs = node.create_llvm_ir(builder, *input_parameters)
        for socket, variable in zip(node.outputs, outputs):
            variables[socket] = variable

        print("BLOCK", next_block)
        builder = ir.IRBuilder(next_block)

    builder.ret(variables[output_socket])

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


def generate_compute_module(required_sockets):
    module_name = "My Module"
    module = ir.Module(module_name)

    output_type = ir.LiteralStructType([s.ir_type for s in required_sockets])
    function_type = ir.FunctionType(output_type, tuple())
    function = ir.Function(module, function_type, name = "Main")
    block = function.append_basic_block("entry")
    builder = ir.IRBuilder(block)

    input_values = {}
    tree = required_sockets[0].id_data
    for node in tree.nodes:
        for socket in iter_unlinked_inputs(node):
            name = get_global_input_name(node, socket)
            source_variable = ir.GlobalVariable(module, socket.ir_type, name)
            source_variable.linkage = "available_externally"
            variable = builder.load(source_variable)
            input_values[socket] = variable

    outputs = generate_function_code(builder, input_values, required_sockets)
    out = builder.load(builder.alloca(output_type, name = "output"))
    for i, variable in enumerate(outputs):
        out = builder.insert_value(out, variable, i)
    builder.ret(out)

    return module


def generate_function_code(builder, unlinked_input_values, required_sockets):
    variables = dict()
    variables.update(unlinked_input_values)

    for socket in required_sockets:
        builder = insert_code_to_calculate_socket(socket, builder, variables)

    outputs = [variables[s] for s in required_sockets]
    return outputs

def insert_code_to_calculate_socket(socket, builder, variables):
    if socket in variables:
        return builder

    if socket.is_output:
        node = socket.node
        for input_socket in node.inputs:
            builder = insert_code_to_calculate_socket(input_socket, builder, variables)

        node_input_values = [variables[s] for s in node.inputs]
        builder, *node_output_values = node.create_llvm_ir(builder, *node_input_values)

        for s, value in zip(node.outputs, node_output_values):
            variables[s] = value
    else:
        origin_socket = get_data_origin_socket(socket)
        builder = insert_code_to_calculate_socket(origin_socket, builder, variables)
        variables[socket] = variables[origin_socket]

    return builder
