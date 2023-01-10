"""Provide a module to create and manipulate quantum circuits."""
from .operation import Operation
from .timepoint import Timepoint
from .qubit import PhysicalQubit  # , VirtualQubit
from .register import Register, QubitRegister, RegisterRegister
from .supportedoperations import _zero_qubit_operations,\
    _one_qubit_operations, _two_qubit_operations

import textwrap


# from IPython.display import display
import json
import numpy as np
from qiskit import QuantumCircuit, execute, Aer
import stim
import copy
import tabulate
tabulate.PRESERVE_WHITESPACE = True


def display_states(head, *args):
    """
    Display states as a pretty table.

    Parameters
    ----------
    head : List
        A list of headings for the table.
    *args : List[List]
        A list of states.

    Returns
    -------
    None.

    """
    if len(args) == 0:
        return
    else:
        comb_tab = copy.deepcopy(args[0])
        for i in range(len(args[0])):
            for v in args[1:]:
                comb_tab[i] += v[i][1:]

    # now delete unneeded lines
    smalltab = []
    for i in range(len(comb_tab)):
        t = comb_tab[i]
        if any(t[1:]):
            line = [t[0]]
            for val in t[1:]:
                real = val.real
                imag = val.imag
                if np.isclose(real, 0) and np.isclose(imag, 0):
                    line += [' ']
                elif np.isclose(imag, 0):
                    line += [f' {real:.3f}']
                elif np.isclose(real, 0):
                    line += [f'{imag:.3f}j']
                elif real > 0:
                    line += [f' {val:.3f}']
                else:
                    line += [f'{val:.3f}']
            smalltab.append(line)

    print(tabulate.tabulate(smalltab, headers=head, colalign=None))


class Circuit:
    """Class for creating and manipulating quantum circuits."""

    def __init__(self):
        """Construct a quantum circuit."""
        self._timepoints = []

        self.register = RegisterRegister('circuit', -2)
        self.register.index = 0

        self.register.append(RegisterRegister('level0', -1))
        self.register.print_structure = self._print_structure

        self.base_address = tuple()

        self._layout_map = None
        self.custom_gates = ''

    @staticmethod
    def simple(num_qubits):
        """
        Create a simple circuit.

        In this circuit there is one register, and user can add operations by
        reference to an integer qubit index. For example, `append('H', 5)`.

        Parameters
        ----------
        num_qubits : int
            Number of qubits. The default is 0.

        Returns
        -------
        circ : Circuit
            An empty circuit.
        """
        circ = Circuit()
        circ.append_register(QubitRegister('', 0, num_qubits))
        circ.base_address = (0, 0)
        return circ

    def __repr__(self):
        """Class description."""
        label_len = len(str(len(self._timepoints)-1))+1
        s = ''
        for i, tp in enumerate(self._timepoints):
            st = textwrap.indent(str(tp), ' '*label_len)
            st = str(i).rjust(label_len-1) + st[label_len-1:] + '\n'
            s += st

        return s

    def __str__(self):
        """Class description."""
        return self.__repr__()

    def __iter__(self):
        """Return iterator for the quantum circuit."""
        for tp in self._timepoints:
            for op in tp:
                yield op

    def __getitem__(self, ind):
        """Make circuit subscriptable."""
        if ind >= 0:
            iterator = self._timepoints
            compare = int.__gt__
            inc = int.__add__
        else:
            iterator = reversed(self._timepoints)
            compare = int.__le__
            inc = int.__sub__

        s = 0
        for tp in iterator:
            L = len(tp)
            if compare(inc(s, L), ind):
                return tp[ind-s]
            else:
                s = inc(s, L)
        else:
            raise IndexError('circuit index out of range')

    def __len__(self):
        """Return number of operations in the quantum circuit."""
        return sum([len(tp) for tp in self._timepoints])

    def _standardize_addresses(self, addresses):

        if type(addresses) is not list:
            not_list = True
            addresses = [addresses]
        else:
            not_list = False

        standardized_addresses = []
        if self.base_address:
            level = self.base_address[0]
        else:
            level = addresses[0][0]
        for input_address in addresses:
            if type(input_address) is tuple:
                full_address = self.base_address + input_address
            elif type(input_address) is int:
                full_address = self.base_address + tuple([input_address])
            else:
                raise Exception('Not a valid address')

            if full_address[0] != level:
                raise Exception('Not all addresses are at the same level')

            self.register.check_address(full_address)
            standardized_addresses.append(full_address)

        if len(set(standardized_addresses)) != len(standardized_addresses):
            raise Exception('Some addresses were repeated')

        if not_list:
            return standardized_addresses[0]
        else:
            return standardized_addresses

    def _apply_encoded_operation(self, op, insert=None):
        crt = self.register[op.targets[0]].constituent_register
        target_register = self.register[crt]
        circ = target_register.code.logical_circuits[op.name]

        if op.is_controlled:
            crc = self.register[op.controls[0]].constituent_register
            # control_register = self.register[crc]

        # if target_register.level == 0:
        if not op.is_controlled:
            for circ_op in circ:
                self.append(op.name, crt+circ_op.targets[0][2:], insert=insert)
        else:
            for circ_op in circ:
                self.append(
                    op.name, crc+circ_op.controls[0][2:],
                    crt+circ_op.targets[0][2:], insert=insert)
        # else:
        #     for circ_op in circ:
        #         self._apply_encoded_operation(circ_op)

    def append(self, *args, insert=None):
        """
        Append a new operation to the circuit.

        Parameters
        ----------
        *args : TYPE
            DESCRIPTION.
        insert : TYPE, optional
            DESCRIPTION. The default is None.

        Raises
        ------
        Exception
            DESCRIPTION.

        Returns
        -------
        None.

        """
        if len(args) == 1 and type(args[0]) is Operation:
            op = args[0]
        elif type(args[0]) is str:
            name = args[0].upper()
            if len(args) == 1 and name in _zero_qubit_operations:
                pass
            elif len(args) == 2 and name in _one_qubit_operations:
                target = self._standardize_addresses(args[1])
                op = Operation(name, [target])
            elif len(args) == 3 and name in _two_qubit_operations:
                [control, target] = self._standardize_addresses([args[1],
                                                                 args[2]])
                op = Operation(name, [target], [control])
            else:
                raise Exception('Not a valid operation')
        else:
            raise Exception('Not a valid operation')

        if op.targets[0][0] == 0:
            if insert is None:
                if len(self._timepoints) == 0 \
                        or not self._timepoints[-1].can_append(op):
                    tp = Timepoint(op)
                    self._timepoints.append(tp)
                else:
                    self._timepoints[-1].append(op)
            elif insert == [1]:
                tp = Timepoint(op)
                self._timepoints.append(tp)
            elif type(insert) is int:
                if not self._timepoints[insert].can_append(op):
                    raise Exception('Cannot add operation to given timepoint.')
                else:
                    self._timepoints[insert].append(op)

        else:
            self._apply_encoded_operation(op, insert=insert)

    # def append(self, *args, insert=None):
    #     if len(args) == 1 and type(args[0]) is Operation:
    #         op = args[0]

    #     else:
    #         if type(args[1]) is tuple:
    #             address1 = self.base_address + args[1]
    #         elif type(args[1]) is int:
    #             address1 = self.base_address + tuple([args[1]])
    #         else:
    #             raise Exception('Not a valid operation')

    #         self.register.check_address(address1)

    #         if len(args) == 2:
    #             op = Operation(args[0], [address1])
    #         else:
    #             if type(args[2]) is tuple:
    #                 address2 = self.base_address + args[2]
    #             elif type(args[2]) is int:
    #                 address2 = self.base_address + tuple([args[2]])
    #             else:
    #                 raise Exception('Not a valid operation')

    #             self.register.check_address(address2)

    #             op = Operation(args[0], [address2], [address1])

    #     if insert is None:
    #         if len(self._timepoints) == 0 \
    #                 or not self._timepoints[-1].can_append(op):
    #             tp = Timepoint(op)
    #             self._timepoints.append(tp)
    #         else:
    #             self._timepoints[-1].append(op)

    #     elif type(insert) is int:
    #         if not self._timepoints[insert].can_append(op):
    #             raise Exception('Cannot add operation to given timepoint.')
    #         else:
    #             self._timepoints[insert].append(op)

    def _append_tp(self, tp):
        self._timepoints.append(tp.copy())

    def append_register(self, register):
        """
        Append a register to the circuit.

        Parameters
        ----------
        register : Register or its subclass
            The register to be appended into the circuit. register.level should
            be set.

        Returns
        -------
        address: tuple
            Address of the appended register

        """
        level = register.level
        for i in range(len(self.register), level+1):
            self.register.append(RegisterRegister(f'level{i}', -1))

        register.index = len(self.register[level])
        self.register[level].append(register)

        return (register.level, register.index)

    def map_to_physical_layout(self, layout='linear'):
        """
        Map the virtual qubits to physical qubits.

        Currently, there is only one inbuilt strategy, 'linear'. However,
        the user may write their own strategy for the mapping.

        Parameters
        ----------
        layout : str, optional
            Placeholder argument for now. The default is 'linear'.

        Returns
        -------
        layout_map: list[list]
            List of the pairs [virtual qubit address, physical qubit index].
        """
        self.physical_register = Register()

        x = list(range(self.num_qubits))
        self.physical_register.elements = [PhysicalQubit(i, 0, x[:i] + x[i+1:])
                                           for i in range(self.num_qubits)]

        qa = self.register[0].qubit_addresses()
        self._layout_map = []
        for i, address in enumerate(qa):
            self.register[0][address].constituent_register = \
                self.physical_register.elements[i]
            self._layout_map.append([(0,) + address, i])

        return self._layout_map

    def _print_structure(self, depth=-1, levels=None):
        if levels is None:
            for reg in self.register:
                reg.print_structure(depth)
        elif type(levels) is int and levels < len(self.register):
            self.register[levels].print_structure(depth)
        elif type(levels) is list:
            for i in levels:
                if i < len(self.registers):
                    self.register[i].print_structure(depth)
        else:
            raise TypeError('levels must be int or a list')

    @ property
    def num_qubits(self):
        """TODO: Allow qubits at any level."""
        return self.register[0].num_qubits

    def apply_circuit(self, other, new_base, insert=None):
        """
        Apply other circuit to this circuit with a new base.

        Parameters
        ----------
        other : Circuit
            The circuit to be applied.
        new_base : tuple
            The base address at which to begin applying other circuit..
        insert : int, optional
            Timepoint index at which to apply the other circuit. The default is
            None.

        Raises
        ------
        Exception
            DESCRIPTION.
        KeyError
            DESCRIPTION.

        Returns
        -------
        None.

        """
        qa = other.register.qubit_addresses()
        L = len(new_base)
        first_address_base = qa[0][0:L]
        if any(address[0:L] != first_address_base for address in qa):
            raise Exception('Base is not common to all qubits.')

        if insert is None:
            for tp in other._timepoints:
                self._append_tp(tp.rebase_qubits(new_base))
        else:
            # decide where to start inserting the timepoints
            if insert >= 0 and insert < len(self._timepoints):
                k = insert
            elif insert == 0 and len(self._timepoints) == 0:
                k = insert
            elif insert < 0 and abs(insert) <= len(self._timepoints):
                k = len(self._timepoints) + insert
            else:
                raise KeyError('Invalid insert point.')

            # check to make sure we can actually insert from this point
            for i, tp in enumerate(other._timepoints):
                if k+i < len(self._timepoints):
                    if not self._timepoints[k+i].can_add(
                            tp.rebase_qubits(new_base)):
                        raise Exception('Cannot add circuits.')

            # add the timepoints
            for i, tp in enumerate(other._timepoints):
                if k+i < len(self._timepoints):
                    self._timepoints[k+i].add(tp.rebase_qubits(new_base))
                else:
                    self._append_tp(tp)

    def __add__(self, other):
        """
        Compose two circuits.

        Parameters
        ----------
        other : Circuit
            The circuit to be added to this one.

        Returns
        -------
        new_circuit : Circuit
            The composition of the two circuits.

        """
        new_circuit = Circuit()

        for op in self:
            new_circuit.append(op)

        for op in other:
            new_circuit.append(op)

        new_circuit.custom_gates = (self.custom_gates
                                    + '\n'
                                    + other.custom_gates)
        return new_circuit

    def qasm(self):
        """
        Convert circuit to qasm string.

        Returns
        -------
        qasm_str : str
            The qasm string of the circuit.

        """
        qasm_str = ''

        for op in self:
            t = self.register[op.targets[0]].constituent_register.index
            if op.name[:7] == 'X_ERROR':
                continue
            elif op.name == 'R':
                op_str = f'reset q[{t}];\n'
            elif op.name == 'MR' or op.name == 'M':
                op_str = f'measure q[{t}] -> c[{t}];\n'
            elif op.name == 'I':
                op_str = f'id q[{t}];\n'
            # elif op.name == 'TICK':
            #     op_str = 'barrier '
            #     for i in range(t, op[3]+1):
            #         op_str += f'q[{i}],'
            #     op_str = op_str[:-1] + ';\n'
            else:
                op_str = op.name.lower() + ' '
                # followed by one or two arguments
                if not op.is_controlled:
                    op_str += f'q[{t}];\n'
                else:
                    c = self.register[op.controls[0]
                                      ].constituent_register.index
                    op_str += f'q[{c}],q[{t}];\n'

            qasm_str += op_str

        qasm_str = 'OPENQASM 2.0;\ninclude "qelib1.inc";\n' \
            + self.custom_gates \
            + f'\nqreg q[{self.num_qubits}];\ncreg c[{self.num_qubits}];\n' \
            + qasm_str

        return qasm_str

    def stim(self):
        """
        Convert circuit to a string that can be imported by stim.

        Returns
        -------
        stim_str : str
            A string suitable for importing by stim.

        """
        stim_str = ''

        for op in self:
            t = self.register[op.targets[0]].constituent_register.index
            if not op.is_controlled:
                stim_str += f'{op.name} {t}\n'
            else:
                c = self.register[op.controls[0]].constituent_register.index
                stim_str += f'{op.name} {c} {t}\n'

        return stim_str

    def quirk(self):
        """
        Convert circuit to a quirk circuit.

        Returns
        -------
        None.
        Prints a url that can opened in the browser.
        """
        validops = {'H', 'X', 'Y', 'Z', 'CX', 'CY', 'CZ'}
        cols = []

        lm_dict = dict()
        for item in self._layout_map:
            lm_dict[item[0]] = item[1]
        for op in self:
            if op.name in validops:
                L = [1 for i in range(self.num_qubits)]
                target_qubit = lm_dict[op.targets[0]]
                if not op.is_controlled:
                    L[target_qubit] = op.draw_str_target
                else:
                    control_qubit = lm_dict[op.controls[0]]
                    L[control_qubit] = "•"
                    L[target_qubit] = op.draw_str_target

                cols.append(L)

        url = 'https://algassert.com/quirk#circuit={"cols":' + \
            json.dumps(cols, ensure_ascii=False) + '}'

        print(url)

    def simulate(self,
                 head=None,
                 incremental=False,
                 return_state=False,
                 print_state=True):
        """
        Simulate the circuit using qiskit.

        Parameters
        ----------
        head : List, optional
            A list of strings that will act as headings. The default is None.
        incremental : bool, optional
            If true, circuit is simulated up to every TICK.
            The default is False.
        return_state : bool, optional
            If the state is returned by the fucntion. The default is False.
        print_state : bool, optional
            If the state is printed. The default is True.

        Returns
        -------
        tab : list
            The state.

        """
        n = self.num_qubits
        if head is None:
            head = ['basis', 'amplitude']

        tab = [[bin(i)[2:][-1::-1].ljust(n, '0')] for i in range(2**n)]

        cur_circ = []

        for ind, op in enumerate(self):
            if ((op.name == 'TICK' and incremental)
                    or ind == len(self)-1):
                cur_circ.append(op)
                cur_circ.append(["id", n-1])
                qc = QuantumCircuit.from_qasm_str(self.qasm())
                job = execute(qc, Aer.get_backend('statevector_simulator'),
                              shots=1,
                              optimization_level=0)
                sv = job.result().get_statevector()
                amps = np.round(sv.data, 3)
                for i in range(2**n):
                    tab[i].append(amps[i])

            else:
                cur_circ.append(op)

        if print_state:
            display_states(head, tab)

        if return_state:
            return tab

    def sample(self,
               return_sample=False,
               print_sample=True):
        """
        Return a sample from the circuit using stim.

        Parameters
        ----------
        return_sample : bool, optional
            If True, return the sample. The default is False.
        print_sample : bool, optional
            If True, print the sample. The default is True.

        Returns
        -------
        TYPE
            DESCRIPTION.

        """
        stim_circ = stim.Circuit(self.stim())
        # print(stim_circ)
        # print("\n\n\n")
        sample = stim_circ.compile_sampler().sample(1)[0]

        if print_sample:
            print(*(1*sample), sep="")

        if return_sample:
            return 1*sample

    def draw(self, filename=None):
        """
        Draw a text version of the circuit.

        Parameters
        ----------
        filename : str, optional
            If filename is provided, then the output will be written to the
            file. Otherwise, it will be printed out. The default is None.

        Returns
        -------
        None.

        """
        dash = '─'
        space = ' '
        vert = '│'

        if not self._layout_map:
            self.map_to_physical_layout()

        lm = self._layout_map.copy()
        lm.sort(key=lambda x: x[1])
        address_label_len = max(map(len, map(lambda x: str(x[0]), lm)))
        index_label_len = 3 + len(str(self.num_qubits))
        label_len = address_label_len + index_label_len
        circ_disp = [list(str(lm[i][0]).ljust(address_label_len)
                          + (' : ' + str(lm[i][1])).rjust(index_label_len)
                     + space) for i in range(self.num_qubits)]
        circ_disp2 = [list(space*(label_len+1))
                      for _ in range(self.num_qubits)]

        circ_tp_line = [space*(label_len+1)]

        for tp in self._timepoints:

            slices = [[]]
            slices_touched_qubits = [[]]
            for op_id, op in enumerate(tp.operations):

                t = self.register[op.targets[0]].constituent_register.index

                if not op.is_controlled:
                    touched_by_op = [t]
                else:
                    c = self.register[op.controls[0]
                                      ].constituent_register.index
                    touched_by_op = list(range(c, t))\
                        + list(range(t, c))
                    touched_by_op.append(touched_by_op[-1]+1)

                for s in range(len(slices)):
                    if len(
                            set(touched_by_op).intersection(
                                set(slices_touched_qubits[s]))) == 0:
                        slices[s].append(op)
                        slices_touched_qubits[s] += touched_by_op
                        break
                else:
                    slices.append([op])
                    slices_touched_qubits.append(touched_by_op)

            circ_tp_line.append('⍿' + space*(3*(len(slices)-1)+2))

            for sl in slices:
                touched_places = []

                for op in sl:
                    t = self.register[op.targets[0]].constituent_register.index

                    if not op.is_controlled:
                        s = dash + op.name + dash
                        circ_disp[t].append(s)
                        circ_disp2[t].append(space*3)
                        touched_places.append(t)

                    elif op.is_controlled:
                        c = self.register[op.controls[0]
                                          ].constituent_register.index
                        vert_places = list(range(c, t)) + list(range(t, c))
                        for i in range(self.num_qubits):
                            if i == c:
                                circ_disp[i].append(
                                    dash + op.draw_str_control + dash)
                                if i == vert_places[0]:
                                    circ_disp2[i].append(space + vert + space)
                                else:
                                    circ_disp2[i].append(space*3)
                                touched_places.append(i)
                            elif i == t:
                                circ_disp[i].append(
                                    dash + op.draw_str_target + dash)
                                if i == vert_places[0]:
                                    circ_disp2[i].append(space + vert + space)
                                else:
                                    circ_disp2[i].append(space*3)
                                touched_places.append(i)
                            elif i in vert_places[1:]:
                                circ_disp[i].append(dash + '┼' + dash)
                                circ_disp2[i].append(space + vert + space)
                                touched_places.append(i)

                for i in range(self.num_qubits):
                    if i not in set(touched_places):
                        circ_disp[i].append(dash*3)
                        circ_disp2[i].append(space*3)

        circ_disp_str = ''.join(circ_tp_line) + '\n'

        for line1, line2 in zip(circ_disp, circ_disp2):
            circ_disp_str += ''.join(line1) + '\n'
            circ_disp_str += ''.join(line2) + '\n'

        if filename is None:
            print(circ_disp_str)
        else:
            with open(filename, 'w') as f:
                f.write(circ_disp_str)
