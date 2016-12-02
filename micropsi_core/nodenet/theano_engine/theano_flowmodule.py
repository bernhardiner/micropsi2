
"""
Flowmodules are a special kind of native modules, with the following properties:

* They have inputs and outputs, in addition to a sub-slot and a sur-gate
* They can be connected to create a flow between Flowmodules
* Flow-terminals are datasources, datatargets and Flow Endndoes
* Flow Endnodes are Flowmodules that have at least one link ending at their sub-slot
* If the sub-slot of an Endnode X receives activation, everything between X and other Flow-terminals (a Flowgraph) is calculated within one nodenet step.
* All Flowmodules that are part of an active Flowgraph show this via activation on their sur-gate

* Flow modules can currently have to kinds of implementation: Theano or python
** Theano-implemented Flowmodules have a buildfunction, that returns a symbolic theano-expression
** Python-implemented Flowmodules hav a runfunction, that can do anything it wants.

* Flowmodules delivering output might decide, that a certain output needs more data, and can choose to return None for that output
  (the total number of return values still must match the number of outputs they define)
  If a Flowgraph receives None as one of its inputs, it is prevented from running, even if it is requested.



"""

from micropsi_core.nodenet.theano_engine.theano_node import TheanoNode
from theano.tensor.var import TensorVariable


class FlowModule(TheanoNode):

    @property
    def inputs(self):
        return self.definition['inputs']

    @property
    def outputs(self):
        return self.definition['outputs']

    def __init__(self, nodenet, partition, parent_uid, uid, type, parameters={}, inputmap={}, outputmap={}, is_copy_of=False):
        super().__init__(nodenet, partition, parent_uid, uid, type, parameters=parameters)
        self.definition = nodenet.native_module_definitions[self.type]
        self.implementation = self.definition['implementation']
        self.outexpression = None
        self.outputmap = {}
        self.inputmap = {}
        self.is_copy_of = is_copy_of
        self._load_functions()
        self.is_part_of_active_graph = False
        for i in self.definition['inputs']:
            self.inputmap[i] = tuple()
        for i in self.definition['outputs']:
            self.outputmap[i] = set()

        for name in inputmap:
            self.inputmap[name] = tuple(inputmap[name])
        for name in outputmap:
            for link in outputmap[name]:
                self.outputmap[name].add(tuple(link))

    def get_flow_data(self, *args, **kwargs):
        inmap = {}
        outmap = {}
        data = {}
        for name in self.inputmap:
            inmap[name] = list(self.inputmap[name])
        for name in self.outputmap:
            outmap[name] = []
            for link in self.outputmap[name]:
                outmap[name].append(list(link))
        data = {
            'flow_module': True,
            'inputmap': inmap,
            'outputmap': outmap,
            'is_copy_of': self.is_copy_of
        }
        return data

    def is_output_connected(self):
        if len(self.outputs) == 0:
            return False
        else:
            return len(set.union(*list(self.outputmap.values()))) > 0

    def is_output_node(self):
        """ Returns true if this is an output-node (that is, if it has at least one link at its sub-slot)"""
        return len(self.get_slot('sub').get_links()) > 0

    def is_input_node(self):
        """ Returns true if this is an input-node (that is, it either has no inputs, or datasources as inputs)"""
        if len(self.inputs) == 0:
            return True
        else:
            return ('worldadapter', 'datasources') in self.inputmap.values()

    def is_requested(self):
        """ Returns true if this node receives sub-activation"""
        return self.get_slot_activations(slot_type='sub') > 0

    def set_theta(self, name, val):
        """ Set the theta value of the given name """
        if self.is_copy_of:
            raise RuntimeError("Shallow copies can not set shared variables")
        self._nodenet.set_theta(self.uid, name, val)

    def get_theta(self, name):
        """ Get the theta value for the given name """
        if self.is_copy_of:
            return self._nodenet.get_theta(self.is_copy_of, name)
        return self._nodenet.get_theta(self.uid, name)

    def set_state(self, name, val):
        if self.is_copy_of:
            raise RuntimeError("Shallow copies can not set states")
        super().set_state(name, val)

    def get_state(self, name):
        if self.is_copy_of:
            return self._nodenet.get_node(self.is_copy_of).get_state(name)
        return super().get_state(name)

    def set_parameter(self, name, val):
        if self.is_copy_of:
            raise RuntimeError("Shallow copies can not set parameters")
        super().set_parameter(name, val)

    def get_parameter(self, name):
        if self.is_copy_of:
            return self._nodenet.get_node(self.is_copy_of).get_parameter(name)
        return super().get_parameter(name)

    def clone_parameters(self):
        if self.is_copy_of:
            return self._nodenet.get_node(self.is_copy_of).clone_parameters()
        return super().clone_parameters()

    def set_input(self, input_name, source_uid, source_output):
        """ Connect a Flowmodule or the worldadapter to the given input of this Flowmodule """
        if input_name not in self.inputs:
            raise NameError("Unknown input %s" % input_name)
        if self.inputmap.get(input_name):
            raise RuntimeError("This input is already connected")
        self.inputmap[input_name] = (source_uid, source_output)

    def unset_input(self, input_name, source_uid, source_output):
        """ Disconnect a Flowmodule or the worldadapter from the given input of this Flowmodule """
        if input_name not in self.inputs:
            raise NameError("Unknown input %s" % input_name)
        self.inputmap[input_name] = tuple()

    def set_output(self, output_name, target_uid, target_input):
        """ Connect a Flowmodule or the worldadapter to the given output of this Flowmodule """
        self.outputmap[output_name].add((target_uid, target_input))

    def unset_output(self, output_name, target_uid, target_input):
        """ Connect a Flowmodule or the worldadapter from the given output of this Flowmodule """
        self.outputmap[output_name].discard((target_uid, target_input))

    def node_function(self):
        """ activates the sur gate if this Flowmodule is part of an active graph """
        self.get_gate('sur').gate_function(1 if self.is_part_of_active_graph else 0)

    def ensure_initialized(self):
        if not self.__initialized and not self.is_copy_of:
            self._initfunction(self._nodenet.netapi, self, self.parameters)
            self.__initialized = True

    def build(self, *inputs):
        """ Builds the node, calls the initfunction if needed, and returns an outexpression.
        This can be either a symbolic theano expression or a python function """
        if self.is_copy_of:
            self._nodenet.get_node(self.is_copy_of).ensure_initialized()
        self.ensure_initialized()
        if self.implementation == 'theano':
            outexpression = self._buildfunction(*inputs, netapi=self._nodenet.netapi, node=self, parameters=self.clone_parameters())

            # add names to the theano expressions returned by the build function.
            # names are added if we received a single expression OR exactly one per documented output,
            # but not for lists of expressions (which may have arbitrary many items).
            name_outexs = outexpression
            if len(self.outputs) == 1:
                name_outexs = [outexpression]
            for out_idx, subexpression in enumerate(name_outexs):
                if isinstance(subexpression, TensorVariable):
                    existing_name = "({})".format(subexpression.name) if subexpression.name is not None else ""
                    subexpression.name = "{}_{}{}".format(self.uid, self.outputs[out_idx], existing_name)

        elif self.implementation == 'python':
            outexpression = self._flowfunction

        self.outexpression = outexpression

        return outexpression

    def _load_functions(self):
        """ Loads the run-/build-/init-functions """
        from importlib.machinery import SourceFileLoader
        import inspect

        sourcefile = self.definition['path']
        module = SourceFileLoader("nodefunctions", sourcefile).load_module()

        if self.definition.get('init_function_name'):
            self._initfunction = getattr(module, self.definition['init_function_name'])
            self.__initialized = False
        else:
            self._initfunction = lambda x, y, z: None
            self.__initialized = True

        if self.implementation == 'theano':
            self._buildfunction = getattr(module, self.definition['build_function_name'])
            self.line_number = inspect.getsourcelines(self._buildfunction)[1]
        elif self.implementation == 'python':
            self._flowfunction = getattr(module, self.definition['run_function_name'])
            self.line_number = inspect.getsourcelines(self._flowfunction)[1]
