from llvmlite import ir
import llvmlite.binding as llvm
from . utils.timing import measureTime
from . utils.nodes import iter_base_nodes_in_tree, iter_compute_node_trees
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

    def get_compute_module(self):
        module_ir = self._create_compute_module()
        module = self._compile_ir_module(module_ir)
        return module

    def _create_compute_module(self):
        tree = self.get_tree()
        inputs = list(getattr(getInputNode(tree), "outputs", []))
        outputs = list(getattr(getOutputNode(tree), "inputs", []))
        module = generate_compute_module(inputs, outputs)
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
    for node in iter_base_nodes_in_tree(tree):
        for socket in iter_unlinked_inputs(node):
            yield node, socket

def iter_input_socket_types(node):
    for socket in node.inputs:
        yield socket.ir_type

def iter_output_socket_pointer_types(node):
    for socket in node.outputs:
        yield socket.ir_type.as_pointer()


def get_global_input_name(node, socket):
    return validify_name(node.name) + " - " + validify_name(socket.identifier)

def validify_name(name):
    return name.replace('"', "")


def getOutputNode(tree):
    return getNodeByType(tree, "cn_OutputNode")

def getInputNode(tree):
    return getNodeByType(tree, "cn_InputNode")

def getNodeByType(tree, idname):
    for node in tree.nodes:
        if node.bl_idname == idname:
            return node


def generate_compute_module(input_sockets, output_sockets):
    assert len(output_sockets) > 0

    module_name = "My Module"
    module = ir.Module(module_name)

    input_types = [s.ir_type for s in input_sockets]
    output_type = ir.LiteralStructType([s.ir_type for s in output_sockets])
    function_type = ir.FunctionType(output_type, input_types)

    function = ir.Function(module, function_type, name = "Main")
    block = function.append_basic_block("entry")
    builder = ir.IRBuilder(block)

    input_values = {}
    tree = output_sockets[0].id_data
    for node in tree.nodes:
        for socket in iter_unlinked_inputs(node):
            name = get_global_input_name(node, socket)
            source_variable = ir.GlobalVariable(module, socket.ir_type, name)
            source_variable.linkage = "available_externally"
            variable = builder.load(source_variable)
            input_values[socket] = variable

    for socket, variable in zip(input_sockets, function.args):
        input_values[socket] = variable

    outputs = generate_function_code(builder, input_values, output_sockets)
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
