import logging
from collections import defaultdict
from six import iterkeys
from spinn_utilities.log import FormatAdapter
from spinn_utilities.timer import Timer
from pacman.exceptions import PacmanConfigurationException
from pacman import operations
from .injection_decorator import injection_context, do_injection
from .algorithm_decorators import (
    scan_packages, get_algorithms, Token)
from .algorithm_metadata_xml_reader import AlgorithmMetadataXmlReader
from pacman.operations import algorithm_reports
from pacman.utilities import file_format_converters
from pacman.executor.token_states import TokenStates

logger = FormatAdapter(logging.getLogger(__name__))


class PACMANAlgorithmExecutor(object):
    """ An executor of PACMAN algorithms where the order is deduced from the\
        input and outputs of the algorithm using an XML description of the\
        algorithm.
    """

    __slots__ = [

        # The timing of algorithms
        "_algorithm_timings",

        # The algorithms to run
        "_algorithms",

        # The inputs passed in from the user
        "_inputs",

        # The completed output tokens
        "_completed_tokens",

        # The type mapping as things flow from input to output
        "_internal_type_mapping",

        # True if timing is to be done
        "_do_timing",

        # True if timing is to be printed
        "_print_timings",

        # True if injection is to be done during the run
        "_do_immediate_injection",

        # True if injection is to be done after the run
        "_do_post_run_injection",

        # True if the inputs are to be injected
        "_inject_inputs",

        # True if direct injection is to be done
        "_do_direct_injection",

        # the flag in the provenance area.
        "_provenance_name",

        # If required a file path to append provenance data to
        "_provenance_path"
    ]

    def __init__(
            self, algorithms, optional_algorithms, inputs, required_outputs,
            tokens, required_output_tokens, xml_paths=None, packages=None,
            do_timings=True, print_timings=False, do_immediate_injection=True,
            do_post_run_injection=False, inject_inputs=True,
            do_direct_injection=True, use_unscanned_annotated_algorithms=True,
            provenance_path=None, provenance_name=None):
        """
        :param algorithms: A list of algorithms that must all be run
        :param optional_algorithms:\
            A list of algorithms that must be run if their inputs are available
        :param inputs: A dict of input type to value
        :param required_outputs: A list of output types that must be generated
        :param tokens:\
            A list of tokens that should be considered to have been generated
        :param required_output_tokens:\
            A list of tokens that should be generated by the end of the run
        :param xml_paths:\
            An optional list of paths to XML files containing algorithm\
            descriptions; if not specified, only detected algorithms will be\
            used (or else those found in packages)
        :param packages:\
            An optional list of packages to scan for decorated algorithms; if\
            not specified, only detected algorithms will be used (or else\
            those specified in packages
        :param do_timings:\
            True if timing information should be printed after each algorithm,\
            False otherwise
        :param do_immediate_injection:\
            Perform injection with objects as they are created; can result in\
            multiple calls to the same inject-annotated methods
        :param do_post_run_injection:\
            Perform injection at the end of the run. This will only set the\
            last object of any type created.
        :param inject_inputs:\
            True if inputs should be injected; only active if one of\
            do_immediate_injection or do_post_run_injection is True.  These\
            variables define when the injection of inputs is done; if\
            immediate injection is True, injection of inputs is done at the\
            start of the run, otherwise it is done at the end.
        :param do_direct_injection:\
            True if direct injection into methods should be supported.  This\
            will allow any of the inputs or generated outputs to be injected\
            into a method
        :param use_unscanned_annotated_algorithms:\
            True if algorithms that have been detected outside of the packages\
            argument specified above should be used
        :param provenance_path:\
            Path to file to append full provenance data to
            If None no provenance is written
        """

        # algorithm timing information
        self._algorithm_timings = list()

        # Store the completed tokens, initially empty
        self._completed_tokens = None

        # pacman mapping objects
        self._algorithms = list()
        self._inputs = inputs

        # define mapping between types and internal values
        self._internal_type_mapping = dict()

        # store timing request
        self._do_timing = do_timings

        # print timings as you go
        self._print_timings = print_timings

        # injection
        self._do_immediate_injection = do_immediate_injection
        self._do_post_run_injection = do_post_run_injection
        self._inject_inputs = inject_inputs
        self._do_direct_injection = do_direct_injection

        if provenance_name is None:
            self._provenance_name = "mapping"
        else:
            self._provenance_name = provenance_name

        self._set_up_pacman_algorithm_listings(
            algorithms, optional_algorithms, xml_paths,
            packages, inputs, required_outputs,
            use_unscanned_annotated_algorithms, tokens, required_output_tokens)

        self._provenance_path = provenance_path

    def _set_up_pacman_algorithm_listings(
            self, algorithms, optional_algorithms, xml_paths, packages, inputs,
            required_outputs, use_unscanned_algorithms, tokens,
            required_output_tokens):
        """ Translates the algorithm string and uses the config XML to create\
            algorithm objects

        :param algorithms: the string representation of the set of algorithms
        :param inputs: list of input types
        :type inputs: iterable(str)
        :param optional_algorithms: list of algorithms which are optional\
            and don't necessarily need to be ran to complete the logic flow
        :type optional_algorithms: iterable(str)
        :param xml_paths: the list of paths for XML configuration data
        :type xml_paths: iterable(str)
        :param required_outputs: \
            the set of outputs that this workflow is meant to generate
        :type required_outputs: iterable(str)
        :param tokens:\
            A list of tokens that should be considered to have been generated\
            as a list of strings
        :param required_output_tokens:\
            A list of tokens that should be generated by the end of the run\
            as a list of strings
        """

        # deduce if the algorithms are internal or external
        algorithms_names = list(algorithms)

        # protect the variable from reference movement during usage
        copy_of_xml_paths = []
        if xml_paths is not None:
            copy_of_xml_paths = list(xml_paths)
        copy_of_packages = []
        if packages is not None:
            copy_of_packages = list(packages)
        copy_of_optional_algorithms = []
        if optional_algorithms is not None:
            copy_of_optional_algorithms = list(optional_algorithms)

        # set up XML reader for standard PACMAN algorithms XML file reader
        # (used in decode_algorithm_data_objects function)
        copy_of_xml_paths.append(operations.algorithms_metdata_file)
        copy_of_xml_paths.append(operations.rigs_algorithm_metadata_file)
        copy_of_xml_paths.append(algorithm_reports.reports_metadata_file)

        # decode the algorithms specs
        xml_decoder = AlgorithmMetadataXmlReader(copy_of_xml_paths)
        algorithm_data_objects = xml_decoder.decode_algorithm_data_objects()
        converter_xml_path = \
            file_format_converters.converter_algorithms_metadata_file
        converter_decoder = AlgorithmMetadataXmlReader([converter_xml_path])
        converters = converter_decoder.decode_algorithm_data_objects()

        # Scan for annotated algorithms
        copy_of_packages.append(operations)
        copy_of_packages.append(algorithm_reports)
        converters.update(scan_packages([file_format_converters]))
        algorithm_data_objects.update(scan_packages(copy_of_packages))
        if use_unscanned_algorithms:
            algorithm_data_objects.update(get_algorithms())

        # get list of all xml's as this is used to exclude xml files from
        # import
        all_xml_paths = list()
        all_xml_paths.extend(copy_of_xml_paths)
        all_xml_paths.append(converter_xml_path)

        # filter for just algorithms we want to use
        algorithm_data = self._get_algorithm_data(
            algorithms_names, algorithm_data_objects)
        optional_algorithms_datas = self._get_algorithm_data(
            copy_of_optional_algorithms, algorithm_data_objects)
        converter_algorithms_datas = self._get_algorithm_data(
            converters.keys(), converters)

        # sort_out_order_of_algorithms for execution
        self._determine_algorithm_order(
            inputs, required_outputs, algorithm_data,
            optional_algorithms_datas, converter_algorithms_datas,
            tokens, required_output_tokens)

    @staticmethod
    def _get_algorithm_data(
            algorithm_names, algorithm_data_objects):
        algorithms = list()
        for algorithm_name in algorithm_names:
            if algorithm_name not in algorithm_data_objects:
                raise PacmanConfigurationException(
                    "Cannot find algorithm {}".format(algorithm_name))
            algorithms.append(algorithm_data_objects[algorithm_name])
        return algorithms

    def _determine_algorithm_order(
            self, inputs, required_outputs, algorithm_data,
            optional_algorithm_data, converter_algorithms_datas,
            tokens, required_output_tokens):
        """ Takes the algorithms and determines which order they need to be\
            executed to generate the correct data objects

        :param inputs: list of input types
        :type inputs: iterable(str)
        :param required_outputs: \
            the set of outputs that this workflow is meant to generate
        :param converter_algorithms_datas: the set of converter algorithms
        :param optional_algorithm_data: the set of optional algorithms
        :rtype: None
        """

        # Go through the algorithms and get all possible outputs
        all_outputs = set(iterkeys(inputs))
        for algorithms in (algorithm_data, optional_algorithm_data):
            for algorithm in algorithms:

                # Get the algorithm output types
                alg_outputs = {
                    output.output_type for output in algorithm.outputs}

                # Remove from the outputs any optional input that is also an
                # output
                for alg_input in algorithm.optional_inputs:
                    for matching in alg_input.get_matching_inputs(alg_outputs):
                        alg_outputs.discard(matching)
                all_outputs.update(alg_outputs)

        # Set up the token tracking and make all specified tokens complete
        token_states = TokenStates()
        for token_name in tokens:
            token = Token(token_name)
            token_states.track_token(token)
            token_states.process_output_token(token)

        # Go through the algorithms and add in the tokens that can be completed
        # by any of the algorithms
        for algorithms in (algorithm_data, optional_algorithm_data):
            for algorithm in algorithms:
                for token in algorithm.generated_output_tokens:
                    if not token_states.is_token_complete(token):
                        token_states.track_token(token)

        # Go through the algorithms and add a fake token for any algorithm that
        # requires an optional token that can't be provided and a fake input
        # for any algorithm that requires an optional input that can't be
        # provided.  This allows us to require the other optional inputs and
        # tokens so that algorithms that provide those items are run before
        # those that can make use of them.
        fake_inputs = set()
        fake_tokens = TokenStates()
        for algorithms in (algorithm_data, optional_algorithm_data):
            for algorithm in algorithms:
                for input_parameter in algorithm.optional_inputs:
                    if not input_parameter.input_matches(all_outputs):
                        fake_inputs.update(
                            input_parameter.get_fake_inputs(all_outputs))
                for token in algorithm.optional_input_tokens:
                    if (not token_states.is_tracking_token(token) and
                            not fake_tokens.is_token_complete(token)):
                        fake_tokens.track_token(token)
                        fake_tokens.process_output_token(token)

        input_types = set(iterkeys(inputs))

        allocated_algorithms = list()
        generated_outputs = set()
        generated_outputs.union(input_types)
        algorithms_to_find = list(algorithm_data)
        optionals_to_use = list(optional_algorithm_data)
        outputs_to_find = self._remove_outputs_which_are_inputs(
            required_outputs, inputs)
        tokens_to_find = self._remove_complete_tokens(
            token_states, required_output_tokens)

        while algorithms_to_find or outputs_to_find or tokens_to_find:

            suitable_algorithm = None
            algorithm_list = None

            # Order of searching - each combination will be attempted in order;
            # the first matching algorithm will be used (and search will stop)
            # Elements are:
            #  1. Algorithm list to search,
            #  2. check generated outputs,
            #  3. require optional inputs)
            order = [

                # Check required algorithms forcing optional inputs
                (algorithms_to_find, False, True),

                # Check optional algorithms forcing optional inputs
                (optionals_to_use, True, True),

                # Check required algorithms without optional inputs
                # - shouldn't need to do this, but might if an optional input
                # is also a generated output of the same algorithm
                (algorithms_to_find, False, False),

                # Check optional algorithms without optional inputs
                # - as above, it shouldn't be necessary but might be if an
                # optional input is also an output of the same algorithm
                (optionals_to_use, True, False),

                # Check converter algorithms
                # (only if they generate something new)
                (converter_algorithms_datas, True, False)
            ]

            for (algorithms, check_outputs, force_required) in order:
                suitable_algorithm, algorithm_list = \
                    self._locate_suitable_algorithm(
                        algorithms, input_types, generated_outputs,
                        token_states, fake_inputs, fake_tokens,
                        check_outputs, force_required)
                if suitable_algorithm is not None:
                    break

            if suitable_algorithm is not None:
                # Remove the value
                self._remove_algorithm_and_update_outputs(
                    algorithm_list, suitable_algorithm, input_types,
                    generated_outputs, outputs_to_find)

                # add the suitable algorithms to the list and take the outputs
                # as new inputs
                allocated_algorithms.append(suitable_algorithm)

                # Mark any tokens generated as complete
                for output_token in suitable_algorithm.generated_output_tokens:
                    token_states.process_output_token(output_token)
                    if token_states.is_token_complete(
                            Token(output_token.name)):
                        tokens_to_find.discard(output_token.name)
            else:

                # Failed to find an algorithm to run!
                algorithms_to_find_names = list()
                for algorithm in algorithms_to_find:
                    algorithms_to_find_names.append(algorithm.algorithm_id)
                optional_algorithms_names = list()
                for algorithm in optional_algorithm_data:
                    optional_algorithms_names.append(algorithm.algorithm_id)
                algorithms_used = list()
                for algorithm in allocated_algorithms:
                    algorithms_used.append(algorithm.algorithm_id)
                algorithm_input_requirement_breakdown = ""
                for algorithm in algorithms_to_find:
                    algorithm_input_requirement_breakdown += \
                        self._deduce_inputs_required_to_run(
                            algorithm, input_types, token_states,
                            fake_inputs, fake_tokens)
                for algorithm in optionals_to_use:
                    algorithm_input_requirement_breakdown += \
                        self._deduce_inputs_required_to_run(
                            algorithm, input_types, token_states,
                            fake_inputs, fake_tokens)
                algorithms_by_output = defaultdict(list)
                algorithms_by_token = defaultdict(list)
                for algorithms in (algorithm_data, optional_algorithm_data):
                    for algorithm in algorithms:
                        for output in algorithm.outputs:
                            algorithms_by_output[output.output_type].append(
                                algorithm.algorithm_id)
                        for token in algorithm.generated_output_tokens:
                            algorithms_by_token[token.name].append(
                                "{}: part={}".format(
                                    algorithm.algorithm_id, token.part))

                raise PacmanConfigurationException(
                    "Unable to deduce a future algorithm to use.\n"
                    "    Inputs: {}\n"
                    "    Fake Inputs: {}\n"
                    "    Outputs to find: {}\n"
                    "    Tokens complete: {}\n"
                    "    Fake tokens complete: {}\n"
                    "    Tokens to find: {}\n"
                    "    Required algorithms remaining to be used: {}\n"
                    "    Optional Algorithms unused: {}\n"
                    "    Functions used: {}\n"
                    "    Algorithm by outputs: {}\n"
                    "    Algorithm by tokens: {}\n"
                    "    Inputs required per function: \n{}\n".format(
                        input_types,
                        fake_inputs,
                        outputs_to_find,
                        token_states.get_completed_tokens(),
                        fake_tokens.get_completed_tokens(),
                        tokens_to_find,
                        algorithms_to_find_names,
                        optional_algorithms_names,
                        algorithms_used,
                        algorithms_by_output,
                        algorithms_by_token,
                        algorithm_input_requirement_breakdown))

        # Test that the outputs are generated
        all_required_outputs_generated = True
        failed_to_generate_output_string = ""
        for output in outputs_to_find:
            if output not in generated_outputs:
                all_required_outputs_generated = False
                failed_to_generate_output_string += ":{}".format(output)

        if not all_required_outputs_generated:
            raise PacmanConfigurationException(
                "Unable to generate outputs {}".format(
                    failed_to_generate_output_string))

        self._algorithms = allocated_algorithms
        self._completed_tokens = token_states.get_completed_tokens()

    def _remove_outputs_which_are_inputs(self, required_outputs, inputs):
        """ Generates the output list which has pruned outputs which are\
            already in the input list

        :param required_outputs: the original output listings
        :param inputs: the inputs given to the executor
        :return: new list of outputs
        :rtype: iterable(str)
        """
        copy_required_outputs = set(required_outputs)
        for input_type in inputs:
            if input_type in copy_required_outputs:
                copy_required_outputs.remove(input_type)
        return copy_required_outputs

    def _remove_complete_tokens(self, tokens, output_tokens):
        return {
            token for token in output_tokens
            if not tokens.is_token_complete(Token(token))
        }

    def _deduce_inputs_required_to_run(
            self, algorithm, inputs, tokens, fake_inputs, fake_tokens):
        left_over_inputs = "            {}: [".format(algorithm.algorithm_id)
        separator = ""
        for algorithm_inputs, extra in (
                (algorithm.required_inputs, ""),
                (algorithm.optional_inputs, " (optional)")):
            for an_input in algorithm_inputs:
                unfound_types = [
                    param_type for param_type in an_input.param_types
                    if param_type not in inputs and
                    param_type not in fake_inputs]
                found_types = [
                    param_type for param_type in an_input.param_types
                    if param_type in inputs or param_type in fake_inputs]
                if unfound_types:
                    left_over_inputs += "{}'{}'{}".format(
                        separator, unfound_types, extra)
                    if found_types:
                        left_over_inputs += " (but found '{}')".format(
                            found_types)
                    separator = ", "
            for a_token in algorithm.required_input_tokens:
                if (not tokens.is_token_complete(a_token) and
                        not fake_tokens.is_token_complete(a_token)):
                    left_over_inputs += "{}'{}'".format(
                        separator, a_token)
                    separator = ", "
        left_over_inputs += "]\n"
        return left_over_inputs

    @staticmethod
    def _remove_algorithm_and_update_outputs(
            algorithm_list, algorithm, inputs, generated_outputs,
            outputs_to_find):
        """ Update data structures

        :param algorithm_list: the list of algorithms to remove algorithm from
        :param algorithm: the algorithm to remove
        :param inputs: the inputs list to update output from algorithm
        :param generated_outputs: \
            the outputs list to update output from algorithm
        :rtype: None
        """
        algorithm_list.remove(algorithm)
        for output in algorithm.outputs:
            inputs.add(output.output_type)
            generated_outputs.add(output.output_type)
            if output.output_type in outputs_to_find:
                outputs_to_find.remove(output.output_type)

    @staticmethod
    def _locate_suitable_algorithm(
            algorithm_list, inputs, generated_outputs, tokens,
            fake_inputs, fake_tokens, check_generated_outputs,
            force_optionals):
        """ Locates a suitable algorithm

        :param algorithm_list: the list of algorithms to choose from
        :param inputs: the inputs available currently
        :param generated_outputs: the current outputs expected to be generated
        :param tokens: the current token tracker
        :param fake_inputs: the optional inputs that will never be available
        :param fake_tokens: the optional tokens that will never be available
        :param check_generated_outputs:\
            True if an algorithm should only be selected if it generates\
            an output not in the list of generated outputs
        :param force_optionals:\
            True if optional inputs/tokens should be considered required
        :return: a suitable algorithm which uses the inputs
        """

        # TODO: This can be made "cleverer" by looking at which algorithms have
        # unsatisfied optional inputs.  The next algorithm to run can then
        # be the next that outputs the most unsatisfied optional inputs for
        # other algorithms from those with the least unsatisfied optional
        # inputs

        # Find the next algorithm which can run now
        for algorithm in algorithm_list:
            # check all inputs
            all_inputs_match = all(
                input_parameter.input_matches(inputs)
                for input_parameter in algorithm.required_inputs)

            # check all required tokens
            if all_inputs_match:
                all_inputs_match = all(
                    tokens.is_token_complete(token)
                    for token in algorithm.required_input_tokens)

            # check all optional inputs
            if all_inputs_match and force_optionals:
                all_inputs_match = all(
                    input_parameter.input_matches(inputs)
                    or input_parameter.input_matches(fake_inputs)
                    for input_parameter in algorithm.optional_inputs)

            # check all optional tokens
            if all_inputs_match and force_optionals:
                all_inputs_match = all(
                    tokens.is_token_complete(token)
                    or fake_tokens.is_token_complete(token)
                    for token in algorithm.optional_input_tokens)

            if all_inputs_match:
                # If the list of generated outputs is not given, we're done now
                if not check_generated_outputs:
                    return algorithm, algorithm_list

                # The list of generated outputs is given, so only use the
                # algorithm if it generates something new, assuming the
                # algorithm generates any outputs at all
                if algorithm.outputs:
                    for output in algorithm.outputs:
                        if (output.output_type not in generated_outputs
                                and output.output_type not in inputs):
                            return algorithm, algorithm_list

                # If the algorithm doesn't generate a unique output,
                # check if it generates a unique token
                if algorithm.generated_output_tokens:
                    for token in algorithm.generated_output_tokens:
                        if not tokens.is_token_complete(token):
                            return algorithm, algorithm_list

        # If no algorithms are available, return None
        return None, algorithm_list

    def execute_mapping(self):
        """ Executes the algorithms

        :rtype: None
        """
        self._internal_type_mapping.update(self._inputs)
        if self._do_direct_injection:
            with injection_context(self._internal_type_mapping):
                self._execute_mapping()
        else:
            self._execute_mapping()

    def _execute_mapping(self):
        if self._inject_inputs and self._do_immediate_injection:
            do_injection(self._inputs)
        new_outputs = dict()
        for algorithm in self._algorithms:
            # set up timer
            timer = None
            if self._do_timing:
                timer = Timer()
                timer.start_timing()

            # Execute the algorithm
            results = algorithm.call(self._internal_type_mapping)

            if self._provenance_path:
                self._report_full_provenance(algorithm, results)

            # handle_prov_data
            if self._do_timing:
                self._update_timings(timer, algorithm)

            if results is not None:
                self._internal_type_mapping.update(results)
                if self._do_immediate_injection and not self._inject_inputs:
                    new_outputs.update(results)

            # Do injection with the outputs produced
            if self._do_immediate_injection:
                do_injection(results)

        # Do injection with all the outputs
        if self._do_post_run_injection:
            if self._inject_inputs:
                do_injection(self._internal_type_mapping)
            else:
                do_injection(new_outputs)

    def get_item(self, item_type):
        """ Get an item from the outputs of the execution

        :param item_type: \
            the item from the internal type mapping to be returned
        :return: the returned item
        """
        if item_type not in self._internal_type_mapping:
            return None
        return self._internal_type_mapping[item_type]

    def get_items(self):
        """ Get all the outputs from a execution

        :return: dictionary of types as keys and values.
        """
        return self._internal_type_mapping

    def get_completed_tokens(self):
        """ Get all of the tokens that have completed as part of this execution

        :return: A list of tokens
        """
        return self._completed_tokens

    @property
    def algorithm_timings(self):
        return self._algorithm_timings

    def _update_timings(self, timer, algorithm):
        time_taken = timer.take_sample()
        if self._print_timings:
            logger.info("Time {} taken by {}",
                        time_taken, algorithm.algorithm_id)
        self._algorithm_timings.append(
            (algorithm.algorithm_id, time_taken, self._provenance_name))

    def _report_full_provenance(self, algorithm, results):
        try:
            with open(self._provenance_path, "a") as provenance_file:
                algorithm.write_provenance_header(provenance_file)
                if algorithm.required_inputs:
                    provenance_file.write("\trequired_inputs:\n")
                    self._report_inputs(provenance_file,
                                        algorithm.required_inputs)
                if algorithm.optional_inputs:
                    provenance_file.write("\toptional_inputs:\n")
                    self._report_inputs(provenance_file,
                                        algorithm.optional_inputs)
                if algorithm.required_input_tokens:
                    provenance_file.write("\trequired_tokens:\n")
                    self._report_tokens(
                        provenance_file, algorithm.required_input_tokens)
                if algorithm.optional_input_tokens:
                    provenance_file.write("\toptional_tokens:\n")
                    self._report_tokens(
                        provenance_file, algorithm.optional_input_tokens)
                if algorithm.outputs:
                    provenance_file.write("\toutputs:\n")
                    for output in algorithm.outputs:
                        variable = results[output.output_type]
                        the_type = self._get_type(variable)
                        provenance_file.write(
                            "\t\t{}:{}\n".format(output.output_type, the_type))
                if algorithm.generated_output_tokens:
                    provenance_file.write("\tgenerated_tokens:\n")
                    self._report_tokens(
                        provenance_file, algorithm.generated_output_tokens)

                provenance_file.write("\n")
        except Exception:
            logger.exception("Exception when attempting to write provenance")

    def _report_inputs(self, provenance_file, inputs):
        for input_parameter in inputs:
            name = input_parameter.name
            for param_type in input_parameter.param_types:
                if param_type in self._internal_type_mapping:
                    variable = self._internal_type_mapping[param_type]
                    the_type = self._get_type(variable)
                    provenance_file.write(
                        "\t\t{}   {}:{}\n".format(name, param_type, the_type))
                    break
            else:
                if len(input_parameter.param_types) == 1:
                    provenance_file.write(
                        "\t\t{}   None of {} provided\n"
                        "".format(name, input_parameter.param_types))
                else:
                    provenance_file.write(
                        "\t\t{}   {} not provided\n"
                        "".format(name, input_parameter.param_types[0]))

    def _report_tokens(self, provenance_file, tokens):
        for token in tokens:
            part = token.part if token.part is not None else ""
            if part == "":
                part = " ({})".format(part)
            provenance_file.write("\t\t{}{}".format(token.name, part))

    def _get_type(self, variable):
        if variable is None:
            return "None"
        the_type = type(variable)
        if the_type in [bool, float, int, str]:
            return variable
        if the_type == set:
            if not variable:
                return "Empty set"
            the_type = "set("
            for item in variable:
                the_type += "{},".format(self._get_type(item))
            the_type += ")"
            return the_type
        elif the_type == list:
            if not variable:
                return "Empty list"
            first_type = type(variable[0])
            if all(isinstance(n, first_type) for n in variable):
                return "list({}) :len{}".format(first_type, len(variable))
        return the_type
