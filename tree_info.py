from . utils.nodes import iter_compute_node_trees
from collections import defaultdict, namedtuple

SocketID = namedtuple("SocketID", ["name", "index"])

class TreeInfo:
    def __init__(self, node_tree):
        nodes = dict(node_tree.nodes)
        links = list(node_tree.links)

        self._insert_nodes(node_tree.nodes)
        self._insert_links(node_tree.links)
        self._find_data_connections()

    def _insert_nodes(self, nodes):
        self.reroute_nodes = set()

        for name, node in nodes.items():
            if node.bl_idname == "NodeReroute":
                self.reroute_nodes.add(name)

    def _insert_links(self, links):
        self.direct_origin = defaultdict(lambda: None)
        self.direct_targets = defaultdict(list)

        for link in links:
            origin_node = link.from_node
            target_node = link.to_node

            origin_socket = link.from_socket
            target_socket = link.to_socket

            origin = SocketID(origin_node.name, list(origin_node.outputs).index(origin_socket))
            target = SocketID(target_node.name, list(target_node.inputs).index(target_socket))

            self.direct_origin[target] = origin
            self.direct_targets[origin].append(target)

    def _find_data_connections(self):
        self.data_origin = defaultdict(lambda: None)
        self.data_targets = defaultdict(list)

        for target, origin in self.direct_origin.items():
            if target.name in self.reroute_nodes:
                continue

            real_origin = self._find_real_data_origin(target, set())
            if real_origin is not None:
                self.data_origin[target] = real_origin
                self.data_targets[real_origin].append(target)

    def _find_real_data_origin(self, target, visited_reroutes):
        direct_origin = self.direct_origin[target]
        if direct_origin is None:
            return None

        if direct_origin.name in visited_reroutes:
            print("Reroute recursion detected")
            return None
        elif direct_origin.name in self.reroute_nodes:
            visited_reroutes.add(direct_origin.name)
            return self._find_real_data_origin(direct_origin, visited_reroutes)
        else:
            return direct_origin


tree_info_by_hash = dict()
updated_trees = set()

def tag_update(tree):
    updated_trees.add(hash(tree))

def update_if_necessary():
    for tree in iter_compute_node_trees():
        tree_hash = hash(tree)
        if tree_hash not in tree_info_by_hash or tree_hash in updated_trees:
            tree_info_by_hash[tree_hash] = TreeInfo(tree)
            updated_trees.discard(tree_hash)


# Access tree info utilities

def iter_unlinked_inputs(node):
    info = tree_info_by_hash[hash(node.id_data)]
    for i, socket in enumerate(node.inputs):
        if info.data_origin[SocketID(node.name, i)] is None:
            yield socket

def iter_linked_inputs(node):
    info = tree_info_by_hash[hash(node.id_data)]
    for i, socket in enumerate(node.inputs):
        if info.data_origin[SocketID(node.name, i)] is not None:
            yield socket

def get_data_origin_socket(socket):
    tree = socket.id_data
    info = tree_info_by_hash[hash(tree)]
    origin = info.data_origin[SocketID(socket.node.name, list(socket.node.inputs).index(socket))]
    if origin is not None:
        return tree.nodes[origin.name].outputs[origin.index]

def get_direct_dependency_node_names(node):
    info = tree_info_by_hash[hash(node.id_data)]
    names = set()
    for i in range(len(node.inputs)):
        origin = info.data_origin[SocketID(node.name, i)]
        if origin is not None:
            names.add(origin.name)
    return names
