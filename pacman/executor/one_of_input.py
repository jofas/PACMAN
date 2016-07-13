from pacman.executor.abstract_input import AbstractInput
from pacman.model.decorators.overrides import overrides


class OneOfInput(AbstractInput):
    """ An input for which one of the input parameters must be matched
    """

    __slots__ = [

        # The inputs
        "_inputs"
    ]

    def __init__(self, inputs):
        """

        :param inputs: The inputs that make up this input
        """
        self._inputs = inputs

    @property
    @overrides(AbstractInput.name)
    def name(self):
        return "One of {}".format(
            [input_type.name for input_type in self._inputs])

    @property
    @overrides(AbstractInput.param_types)
    def param_types(self):
        return "One of {}".format(
            [input_type.param_types for input_type in self._inputs])

    @overrides(AbstractInput.get_inputs_by_name)
    def get_inputs_by_name(self, inputs):
        for input_type in self._inputs:
            match = input_type.get_inputs_by_name(inputs)

            # If the match was found, return it
            if match is not None:
                return match
        return None
