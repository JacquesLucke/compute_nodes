import bpy
from .. compute_node import ComputeNode

def iter_compute_nodes_in_tree(tree):
    for node in tree.nodes:
        if isinstance(node, ComputeNode):
            yield node

def iter_compute_node_trees():
    for node_tree in bpy.data.node_groups:
        if node_tree.bl_idname == "cn_ComputeNodeTree":
            yield node_tree
