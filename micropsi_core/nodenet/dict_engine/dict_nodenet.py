__author__ = 'rvuine'

import micropsi_core.tools
import json
import os

import warnings
from micropsi_core.nodenet.node import Node, Nodetype, STANDARD_NODETYPES
from threading import Lock
import logging
from micropsi_core.nodenet.nodenet import Nodenet, NODENET_VERSION, NodenetLockException
from micropsi_core.nodenet.nodespace import Nodespace
from micropsi_core.nodenet.monitor import Monitor

from copy import deepcopy


class DictNodenet(Nodenet):
    """Main data structure for MicroPsi agents,

    Contains the net entities and runs the activation spreading. The nodenet stores persistent data.

    Attributes:
        state: a dict of persistent nodenet data; everything stored within the state can be stored and exported
        uid: a unique identifier for the node net
        name: an optional name for the node net
        filename: the path and file name to the file storing the persisted net data
        nodespaces: a dictionary of node space UIDs and respective node spaces
        nodes: a dictionary of node UIDs and respective nodes
        links: a dictionary of link UIDs and respective links
        gate_types: a dictionary of gate type names and the individual types of gates
        slot_types: a dictionary of slot type names and the individual types of slots
        node_types: a dictionary of node type names and node type definitions
        world: an environment for the node net
        worldadapter: an actual world adapter object residing in a world implementation, provides interface
        owner: an id of the user who created the node net
        step: the current simulation step of the node net
    """

    @property
    def data(self):
        data = super(DictNodenet, self).data
        data['links'] = self.construct_links_dict()
        data['nodes'] = self.construct_nodes_dict()
        data['nodespaces'] = self.construct_nodespaces_dict("Root")
        data['monitors'] = self.construct_monitors_dict()
        data['version'] = self.__version
        return data

    @property
    def current_step(self):
        return self.__step

    def __init__(self, filename, name="", worldadapter="Default", world=None, owner="", uid=None, nodetypes={}, native_modules={}):
        """Create a new MicroPsi agent.

        Arguments:
            filename: the path and filename of the agent
            agent_type (optional): the interface of this agent to its environment
            name (optional): the name of the agent
            owner (optional): the user that created this agent
            uid (optional): unique handle of the agent; if none is given, it will be generated
        """

        super(DictNodenet, self).__init__(name or os.path.basename(filename), worldadapter, world, owner, uid)

        self.__version = NODENET_VERSION  # used to check compatibility of the node net data
        self.__step = 0
        self.settings = {}

        self.filename = filename
        if world and worldadapter:
            self.worldadapter = worldadapter

        self.__nodes = {}
        self.__nodetypes = nodetypes
        self.__native_modules = native_modules
        self.__nodespaces = {}
        self.__nodespaces["Root"] = Nodespace(self, None, (0, 0), name="Root", uid="Root")

        self.__monitors = {}
        self.__locks = {}
        self.__nodes_by_coords = {}

        self.load()

    def load(self, string=None):
        """Load the node net from a file"""
        # try to access file
        with self.netlock:

            initfrom = {}

            if string:
                self.logger.info("Loading nodenet %s from string", self.name)
                try:
                    initfrom.update(json.loads(string))
                except ValueError:
                    warnings.warn("Could not read nodenet data from string")
                    return False
            else:
                try:
                    self.logger.info("Loading nodenet %s from file %s", self.name, self.filename)
                    with open(self.filename) as file:
                        initfrom.update(json.load(file))
                except ValueError:
                    warnings.warn("Could not read nodenet data")
                    return False
                except IOError:
                    warnings.warn("Could not open nodenet file")

            if self.__version == NODENET_VERSION:
                self.initialize_nodenet(initfrom)
                return True
            else:
                raise NotImplementedError("Wrong version of nodenet data, cannot import.")

    def reload_native_modules(self, native_modules):
        """ reloads the native-module definition, and their nodefunctions
        and afterwards reinstantiates the nodenet."""
        self.__native_modules = {}
        for key in native_modules:
            self.__native_modules[key] = Nodetype(nodenet=self, **native_modules[key])
            self.__native_modules[key].reload_nodefunction()
        saved = self.data
        self.clear()
        self.merge_data(saved)

    def initialize_nodespace(self, id, data):
        if id not in self.__nodespaces:
            # move up the nodespace tree until we find an existing parent or hit root
            while id != 'Root' and data[id].get('parent_nodespace') not in self.__nodespaces:
                self.initialize_nodespace(data[id]['parent_nodespace'], data)
            self.__nodespaces[id] = Nodespace(self,
                data[id].get('parent_nodespace'),
                data[id].get('position'),
                name=data[id].get('name', 'Root'),
                uid=id,
                index=data[id].get('index'),
                gatefunction_strings=data[id].get('gatefunctions'))

    def initialize_nodenet(self, initfrom):
        """Called after reading new nodenet state.

        Parses the nodenet state and set up the non-persistent data structures necessary for efficient
        computation of the node net
        """

        nodetypes = {}
        for type, data in self.__nodetypes.items():
            nodetypes[type] = Nodetype(nodenet=self, **data)
        self.__nodetypes = nodetypes

        native_modules = {}
        for type, data in self.__native_modules.items():
            native_modules[type] = Nodetype(nodenet=self, **data)
        self.__native_modules = native_modules

        # set up nodespaces; make sure that parent nodespaces exist before children are initialized
        self.__nodespaces = {}
        self.__nodespaces["Root"] = Nodespace(self, None, (0, 0), name="Root", uid="Root")

        # now merge in all init data (from the persisted file typically)
        self.merge_data(initfrom)

    def construct_links_dict(self):
        data = {}
        for node_uid in self.get_node_uids():
            links = self.get_node(node_uid).get_associated_links()
            for link in links:
                data[link.uid] = link.data
        return data

    def construct_nodes_dict(self, max_nodes=-1):
        data = {}
        i = 0
        for node_uid in self.get_node_uids():
            i += 1
            data[node_uid] = self.get_node(node_uid).data
            if max_nodes > 0 and i > max_nodes:
                break
        return data

    def construct_nodespaces_dict(self, nodespace_uid):
        data = {}
        for nodespace_candidate_uid in self.get_nodespace_uids():
            if self.get_nodespace(nodespace_candidate_uid).parent_nodespace == nodespace_uid or nodespace_candidate_uid == nodespace_uid:
                data[nodespace_candidate_uid] = self.get_nodespace(nodespace_candidate_uid).data
        return data

    def construct_monitors_dict(self):
        data = {}
        for monitor_uid in self.__monitors:
            data[monitor_uid] = self.__monitors[monitor_uid].data
        return data

    def get_nodetype(self, type):
        """ Returns the nodetpype instance for the given nodetype or native_module or None if not found"""
        if type in self.__nodetypes:
            return self.__nodetypes[type]
        else:
            return self.__native_modules.get(type)

    def get_nodespace_area_data(self, nodespace, x1, x2, y1, y2):
        x_range = (x1 - (x1 % 100), 100 + x2 - (x2 % 100), 100)
        y_range = (y1 - (y1 % 100), 100 + y2 - (y2 % 100), 100)

        world_uid = self.world.uid if self.world is not None else None

        data = {
            'links': {},
            'nodes': {},
            'name': self.name,
            'max_coords': self.max_coords,
            'is_active': self.is_active,
            'current_step': self.current_step,
            'nodespaces': self.construct_nodespaces_dict(nodespace),
            'world': world_uid,
            'worldadapter': self.worldadapter
        }
        if self.user_prompt is not None:
            data['user_prompt'] = self.user_prompt.copy()
            self.user_prompt = None
        links = []
        followupnodes = []
        for x in range(*x_range):
            if x in self.__nodes_by_coords:
                for y in range(*y_range):
                    if y in self.__nodes_by_coords[x]:
                        for uid in self.__nodes_by_coords[x][y]:
                            if self.get_node(uid).parent_nodespace == nodespace:  # maybe sort directly by nodespace??
                                data['nodes'][uid] = self.get_node(uid).data
                                links.extend(self.get_node(uid).get_associated_links())
                                followupnodes.extend(self.get_node(uid).get_associated_node_uids())
        for link in links:
            data['links'][link.uid] = link.data
        for uid in followupnodes:
            if uid not in data['nodes']:
                data['nodes'][uid] = self.get_node(uid).data
        return data

    def update_node_positions(self):
        """ recalculates the position hash """
        self.__nodes_by_coords = {}
        self.max_coords = {'x': 0, 'y': 0}
        for uid in self.get_node_uids():
            pos = self.get_node(uid).position
            xpos = int(pos[0] - (pos[0] % 100))
            ypos = int(pos[1] - (pos[1] % 100))
            if xpos not in self.__nodes_by_coords:
                self.__nodes_by_coords[xpos] = {}
                if xpos > self.max_coords['x']:
                    self.max_coords['x'] = xpos
            if ypos not in self.__nodes_by_coords[xpos]:
                self.__nodes_by_coords[xpos][ypos] = []
                if ypos > self.max_coords['y']:
                    self.max_coords['y'] = ypos
            self.__nodes_by_coords[xpos][ypos].append(uid)

    def delete_node(self, node_uid):
        if node_uid in self.__nodespaces:
            affected_entity_ids = self.__nodespaces[node_uid].get_known_ids()
            for uid in affected_entity_ids:
                self.delete_node(uid)
            parent_nodespace = self.__nodespaces.get(self.__nodespaces[node_uid].parent_nodespace)
            if parent_nodespace and parent_nodespace.is_entity_known_as('nodespaces', node_uid):
                parent_nodespace._unregister_entity('nodespaces', node_uid)
            del self.__nodespaces[node_uid]
        else:
            node = self.__nodes[node_uid]
            node.unlink_completely()
            parent_nodespace = self.__nodespaces.get(self.__nodes[node_uid].parent_nodespace)
            parent_nodespace._unregister_entity('nodes', node_uid)
            if self.__nodes[node_uid].type == "Activator":
                parent_nodespace.unset_activator_value(self.__nodes[node_uid].get_parameter('type'))
            del self.__nodes[node_uid]
            self.update_node_positions()

    def get_nodespace_data(self, nodespace_uid, max_nodes):
        """returns the nodes and links in a given nodespace"""
        data = {
            'nodes': self.construct_nodes_dict(max_nodes),
            'links': self.construct_links_dict(),
            'nodespaces': self.construct_nodespaces_dict(nodespace_uid),
            'monitors': self.construct_monitors_dict()
        }
        if self.user_prompt is not None:
            data['user_prompt'] = self.user_prompt.copy()
            self.user_prompt = None
        return data

    def clear(self):
        self.__nodes = {}
        self.__monitors = {}

        self.__nodes_by_coords = {}
        self.max_coords = {'x': 0, 'y': 0}

        self.__nodespaces = {}
        Nodespace(self, None, (0, 0), "Root", "Root")

    def _register_node(self, node):
        self.__nodes[node.uid] = node

    def _register_nodespace(self, nodespace):
        self.__nodespaces[nodespace.uid] = nodespace

    def _register_monitor(self, monitor):
        self.__monitors[monitor.uid] = monitor

    def _unregister_monitor(self, monitor_uid):
        del self.__monitors[monitor_uid]

    def merge_data(self, nodenet_data):
        """merges the nodenet state with the current node net, might have to give new UIDs to some entities"""

        # Because of the horrible initialize_nodenet design that replaces existing dictionary objects with
        # Python objects between initial loading and first use, none of the nodenet setup code is reusable.
        # Instantiation should be a state-independent method or a set of state-independent methods that can be
        # called whenever new data needs to be merged in, initially or later on.
        # Potentially, initialize_nodenet can be replaced with merge_data.

        # net will have the name of the one to be merged into us
        self.name = nodenet_data['name']

        # merge in spaces, make sure that parent nodespaces exist before children are initialized
        nodespaces_to_merge = set(nodenet_data.get('nodespaces', {}).keys())
        for nodespace in nodespaces_to_merge:
            self.initialize_nodespace(nodespace, nodenet_data['nodespaces'])

        # merge in nodes
        for uid in nodenet_data.get('nodes', {}):
            data = nodenet_data['nodes'][uid]
            if data['type'] in self.__nodetypes or data['type'] in self.__native_modules:
                self.__nodes[uid] = Node(self, **data)
                pos = self.__nodes[uid].position
                xpos = int(pos[0] - (pos[0] % 100))
                ypos = int(pos[1] - (pos[1] % 100))
                if xpos not in self.__nodes_by_coords:
                    self.__nodes_by_coords[xpos] = {}
                    if xpos > self.max_coords['x']:
                        self.max_coords['x'] = xpos
                if ypos not in self.__nodes_by_coords[xpos]:
                    self.__nodes_by_coords[xpos][ypos] = []
                    if ypos > self.max_coords['y']:
                        self.max_coords['y'] = ypos
                self.__nodes_by_coords[xpos][ypos].append(uid)
            else:
                warnings.warn("Invalid nodetype %s for node %s" % (data['type'], uid))

        # merge in links
        for uid in nodenet_data.get('links', {}):
            data = nodenet_data['links'][uid]
            if data['source_node_uid'] in self.__nodes:
                source_node = self.__nodes[data['source_node_uid']]
                source_node.link(data['source_gate_name'],
                                 data['target_node_uid'],
                                 data['target_slot_name'],
                                 data['weight'],
                                 data['certainty'])

        # merge in monitors
        for uid in nodenet_data.get('monitors', {}):
            self.__monitors[uid] = Monitor(self, **nodenet_data['monitors'][uid])

    def copy_nodes(self, nodes, nodespaces, target_nodespace=None, copy_associated_links=True):
        """takes a dictionary of nodes and merges them into the current nodenet.
        Links between these nodes will be copied, too.
        If the source nodes are within the current nodenet, it is also possible to retain the associated links.
        If the source nodes originate within a different nodespace (either because they come from a different
        nodenet, or because they are copied into a different nodespace), the associated links (i.e. those that
        link the copied nodes to elements that are themselves not being copied), can be retained, too.
        Nodes and links may need to receive new UIDs to avoid conflicts.

        Arguments:
            nodes: a dictionary of node_uids with nodes
            target_nodespace: if none is given, we copy into the same nodespace of the originating nodes
            copy_associated_links: if True, also copy connections to not copied nodes
        """
        rename_nodes = {}
        rename_nodespaces = {}
        if not target_nodespace:
            target_nodespace = "Root"
            # first, check for nodespace naming conflicts
        for nodespace_uid in nodespaces:
            if nodespace_uid in self.__nodespaces:
                rename_nodespaces[nodespace_uid] = micropsi_core.tools.generate_uid()
            # create the nodespaces
        for nodespace_uid in nodespaces:
            original = nodespaces[nodespace_uid]
            uid = rename_nodespaces.get(nodespace_uid, nodespace_uid)

            Nodespace(self, target_nodespace,
                position=original.position,
                name=original.name,
                gatefunction_strings=deepcopy(original.get_gatefunction_strings()),
                uid=uid)

        # set the parents (needs to happen in seperate loop to ensure nodespaces are already created
        for nodespace_uid in nodespaces:
            if nodespaces[nodespace_uid].parent_nodespace in nodespaces:
                uid = rename_nodespaces.get(nodespace_uid, nodespace_uid)
                target_nodespace = rename_nodespaces.get(nodespaces[nodespace_uid].parent_nodespace)
                self.__nodespaces[uid].parent_nodespace = target_nodespace

        # copy the nodes
        for node_uid in nodes:
            if node_uid in self.__nodes:
                rename_nodes[node_uid] = micropsi_core.tools.generate_uid()
                uid = rename_nodes[node_uid]
            else:
                uid = node_uid

            original = nodes[node_uid]
            target = original.parent_nodespace if original.parent_nodespace in nodespaces else target_nodespace
            target = rename_nodespaces.get(target, target)

            Node(self, target,
                position=original.position,
                name=original.name,
                type=original.type,
                uid=uid,
                parameters=deepcopy(original.clone_parameters()),
                gate_parameters=original.get_gate_parameters()
            )

        # copy the links
        links_to_copy = set()
        for node_uid in nodes:
            node = nodes[node_uid]
            for slot in node.get_slot_types():
                for link in node.get_slot(slot).get_links():
                    if link.source_node.uid in nodes or (copy_associated_links
                                                         and link.source_node.uid in self.__nodes):
                        links_to_copy.add(link)
            for gate in node.get_gate_types():
                for link in node.get_gate(gate).get_links():
                    if link.target_node.uid in nodes or (copy_associated_links
                                                         and link.target_node.uid in self.__nodes):
                        links_to_copy.add(link)
        for link in links_to_copy:
            source_node = self.__nodes[rename_nodes.get(link.source_node.uid, link.source_node.uid)]
            source_node.link(
                link.source_gate.type,
                link.target_node.uid,
                link.target_slot.type,
                link.weight,
                link.certainty)

    def step(self):
        """perform a simulation step"""
        self.user_prompt = None
        if self.world is not None and self.world.agents is not None and self.uid in self.world.agents:
            self.world.agents[self.uid].snapshot()      # world adapter snapshot
                                                        # TODO: Not really sure why we don't just know our world adapter,
                                                        # but instead the world object itself

        with self.netlock:
            self.propagate_link_activation(self.__nodes.copy())

            self.timeout_locks()

            activators = self.get_activators()
            nativemodules = self.get_nativemodules()
            everythingelse = self.__nodes.copy()
            for key in nativemodules:
                del everythingelse[key]

            self.calculate_node_functions(activators)       # activators go first
            self.calculate_node_functions(nativemodules)    # then native modules, so API sees a deterministic state
            self.calculate_node_functions(everythingelse)   # then all the peasant nodes get calculated

            self.netapi._step()

            self.__step += 1
            for uid in self.__monitors:
                self.__monitors[uid].step(self.__step)
            for uid, node in activators.items():
                node.activation = self.__nodespaces[node.parent_nodespace].get_activator_value(node.get_parameter('type'))

    def propagate_link_activation(self, nodes, limit_gatetypes=None):
        """ the linkfunction
            propagate activation from gates to slots via their links. returns the nodes that received activation.
            Arguments:
                nodes: the dict of nodes to consider
                limit_gatetypes (optional): a list of gatetypes to restrict the activation to links originating
                    from the given slottypes.
        """
        for uid, node in nodes.items():
            node.reset_slots()

        # propagate sheaf existence
        for uid, node in nodes.items():
            for gate_type in node.get_gate_types():
                if limit_gatetypes is None or gate_type in limit_gatetypes:
                    gate = node.get_gate(gate_type)
                    if gate.parameters['spreadsheaves'] is True:
                        for sheaf in gate.sheaves:
                            for link in gate.get_links():
                                for slotname in link.target_node.get_slot_types():
                                    if sheaf not in link.target_node.get_slot(slotname).sheaves and link.target_node.type != "Actor":
                                        link.target_node.get_slot(slotname).sheaves[sheaf] = dict(
                                            uid=gate.sheaves[sheaf]['uid'],
                                            name=gate.sheaves[sheaf]['name'],
                                            activation=0)

        # propagate activation
        for uid, node in nodes.items():
            for gate_type in node.get_gate_types():
                if limit_gatetypes is None or gate_type in limit_gatetypes:
                    gate = node.get_gate(gate_type)
                    for link in gate.get_links():
                        for sheaf in gate.sheaves:
                            if link.target_node.type == "Actor":
                                sheaf = "default"

                            if sheaf in link.target_slot.sheaves:
                                link.target_slot.sheaves[sheaf]['activation'] += \
                                    float(gate.sheaves[sheaf]['activation']) * float(link.weight)  # TODO: where's the string coming from?
                            elif sheaf.endswith(link.target_node.uid):
                                upsheaf = sheaf[:-(len(link.target_node.uid) + 1)]
                                link.target_slot.sheaves[upsheaf]['activation'] += \
                                    float(gate.sheaves[sheaf]['activation']) * float(link.weight)  # TODO: where's the string coming from?

    def timeout_locks(self):
        """
        Removes all locks that time out in the current step
        """
        locks_to_delete = []
        for lock, data in self.__locks.items():
            self.__locks[lock] = (data[0] + 1, data[1], data[2])
            if data[0] + 1 >= data[1]:
                locks_to_delete.append(lock)
        for lock in locks_to_delete:
            del self.__locks[lock]

    def calculate_node_functions(self, nodes):
        """for all given nodes, call their node function, which in turn should update the gate functions
           Arguments:
               nodes: the dict of nodes to consider
        """
        for uid, node in nodes.copy().items():
            node.node_function()

    def get_node(self, uid):
        return self.__nodes[uid]

    def get_nodespace(self, uid):
        return self.__nodespaces[uid]

    def get_node_uids(self):
        return list(self.__nodes.keys())

    def get_nodespace_uids(self):
        return list(self.__nodespaces.keys())

    def is_node(self, uid):
        return uid in self.__nodes

    def is_nodespace(self, uid):
        return uid in self.__nodespaces

    def get_monitor(self, uid):
        return self.__monitors[uid]

    def get_nativemodules(self, nodespace=None):
        """Returns a dict of native modules. Optionally filtered by the given nodespace"""
        nodes = self.__nodes if nodespace is None else self.__nodespaces[nodespace].get_known_ids('nodes')
        nativemodules = {}
        for uid in nodes:
            if self.__nodes[uid].type not in STANDARD_NODETYPES:
                nativemodules.update({uid: self.__nodes[uid]})
        return nativemodules

    def get_activators(self, nodespace=None, type=None):
        """Returns a dict of activator nodes. OPtionally filtered by the given nodespace and the given type"""
        nodes = self.__nodes if nodespace is None else self.__nodespaces[nodespace].get_known_ids('nodes')
        activators = {}
        for uid in nodes:
            if self.__nodes[uid].type == 'Activator':
                if type is None or type == self.__nodes[uid].get_parameter('type'):
                    activators.update({uid: self.__nodes[uid]})
        return activators

    def get_sensors(self, nodespace=None):
        """Returns a dict of all sensor nodes. Optionally filtered by the given nodespace"""
        nodes = self.__nodes if nodespace is None else self.__nodespaces[nodespace].get_known_ids('nodes')
        sensors = {}
        for uid in nodes:
            if self.__nodes[uid].type == 'Sensor':
                sensors[uid] = self.__nodes[uid]
        return sensors

    def get_actors(self, nodespace=None):
        """Returns a dict of all sensor nodes. Optionally filtered by the given nodespace"""
        nodes = self.__nodes if nodespace is None else self.__nodespaces[nodespace].get_known_ids('nodes')
        actors = {}
        for uid in nodes:
            if self.__nodes[uid].type == 'Actor':
                actors[uid] = self.__nodes[uid]
        return actors

    def set_link_weight(self, source_node_uid, gate_type, target_node_uid, slot_type, weight=1, certainty=1):
        """Set weight of the given link."""

        source_node = self.get_node(source_node_uid)
        if source_node is None:
            return False

        link = source_node.link(gate_type, target_node_uid, slot_type, weight, certainty)
        if link is None:
            return False
        else:
            return True

    def create_link(self, source_node_uid, gate_type, target_node_uid, slot_type, weight=1, certainty=1):
        """Creates a new link.

        Arguments.
            source_node_uid: uid of the origin node
            gate_type: type of the origin gate (usually defines the link type)
            target_node_uid: uid of the target node
            slot_type: type of the target slot
            weight: the weight of the link (a float)
            certainty (optional): a probabilistic parameter for the link

        Returns:
            the link if successful,
            None if failure
        """

        source_node = self.get_node(source_node_uid)
        if source_node is None:
            return False, None

        link = source_node.link(gate_type, target_node_uid, slot_type, weight, certainty)
        if link is None:
            return False, None
        else:
            return True, link

    def delete_link(self, source_node_uid, gate_type, target_node_uid, slot_type):
        """Delete the given link."""

        source_node = self.get_node(source_node_uid)
        if source_node is None:
            return False, None
        source_node.unlink(gate_type, target_node_uid, slot_type)
        return True

    def is_locked(self, lock):
        """Returns true if a lock of the given name exists"""
        return lock in self.__locks

    def is_locked_by(self, lock, key):
        """Returns true if a lock of the given name exists and the key used is the given one"""
        return lock in self.__locks and self.__locks[lock][2] == key

    def lock(self, lock, key, timeout=100):
        """Creates a lock with the given name that will time out after the given number of steps
        """
        if self.is_locked(lock):
            raise NodenetLockException("Lock %s is already locked." % lock)
        self.__locks[lock] = (0, timeout, key)

    def unlock(self, lock):
        """Removes the given lock
        """
        del self.__locks[lock]