import bpy
from llvmlite import ir
from . compute_node import ComputeNode

class FloatMathNode(bpy.types.Node, ComputeNode):
    bl_idname = "cn_FloatMathNode"
    bl_label = "Float Math"

    def init(self, context):
        self.inputs.new("cn_FloatSocket", "A", "a")
        self.inputs.new("cn_FloatSocket", "B", "b")
        self.outputs.new("cn_FloatSocket", "Result", "result")

    def create_llvm_ir(self, builder, a, b):
        res = builder.fadd(a, b, name = "result")
        return builder, res
