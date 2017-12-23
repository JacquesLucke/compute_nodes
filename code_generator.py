import re
from llvmlite import ir
import llvmlite.binding as llvm
from . utils.nodes import iter_compute_nodes_in_tree
from . tree_info import iter_unlinked_inputs

target = llvm.Target.from_default_triple()
target_machine = target.create_target_machine()
empty_module = llvm.parse_assembly("")
engine = llvm.create_mcjit_compiler(empty_module, target_machine)


def compile_ir(llvm_ir):
    module = llvm.parse_assembly(llvm_ir)
    module.verify()
    engine.add_module(module)
    engine.finalize_object()

def create_module(tree):
    module = ir.Module()

    for node in iter_compute_nodes_in_tree(tree):
        create_node_function(module, node)

    print(module)

def create_globals_module(tree):
    module = ir.Module()
    for node in iter_compute_nodes_in_tree(tree):
        for socket in iter_unlinked_inputs(node):
            name = get_global_input_name(node, name)
            variable = ir.GlobalVariable(module, socket.ir_type, name)
    print(module)

def get_global_input_name(node, socket):
    return validify_name(node.name) + " - " + validify_name(socket.identifier)

def validify_name(name):
    return name.replace('"', "")


def create_node_function(module, node):
    input_types = list(iter_input_socket_types(node))
    output_types = list(iter_output_socket_pointer_types(node))

    function_type = ir.FunctionType(ir.VoidType(), input_types + output_types)
    function = ir.Function(module, function_type, name = node.name)

    input_args = function.args[:len(input_types)]
    output_args = function.args[len(input_types):]

    output_variables = node.create_llvm_ir(function, *input_args)

    block = function.append_basic_block()
    builder = ir.IRBuilder(block)
    for var, arg in zip(output_variables, output_args):
        builder.store(var, arg)

def iter_input_socket_types(node):
    for socket in node.inputs:
        yield socket.ir_type

def iter_output_socket_pointer_types(node):
    for socket in node.outputs:
        yield socket.ir_type.as_pointer()


def compute():
    import bpy
    node = bpy.data.node_groups[0].nodes[0]


    module = ir.Module()
    function_type = ir.FunctionType(ir.FloatType(), (ir.FloatType(), ))
    function = ir.Function(module, function_type, name = "run hello")
    block = function.append_basic_block()
    builder = ir.IRBuilder(block)

    input_variables = []
    for socket in node.inputs:
        global_variable = ir.GlobalVariable(module, socket.ir_type, socket.identifier)
        #global_variable.linkage = "private"
        global_variable.initializer = ir.Constant(socket.ir_type, 4)
        variable = builder.load(global_variable)
        input_variables.append(variable)
    result = node.create_llvm_ir(builder, *input_variables)
    builder.ret(result)
    print(module)

    compile_ir(str(module))

    from ctypes import CFUNCTYPE, c_float, pointer, POINTER
    f = engine.get_function_address("run hello")
    node.inputs[0].update_at_address(engine.get_global_value_address("a"))
    node.inputs[1].update_at_address(engine.get_global_value_address("b"))


    cfunc = CFUNCTYPE(c_float)(f)
    print("Result:", cfunc())
