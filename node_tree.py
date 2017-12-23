import bpy
from . tree_info import tag_update

class ComputeNodeTree(bpy.types.NodeTree):
    bl_idname = "cn_ComputeNodeTree"
    bl_label = "Compute"
    bl_icon = "SCRIPTPLUGINS"

    def update(self):
        tag_update(self)
