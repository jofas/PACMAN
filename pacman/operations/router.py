import logging
from pacman.utilities import reports

logger = logging.getLogger(__name__)


class Router:
    """ Used to find routes through a machine
    """

    def __init__(self, machine, report_states, placements, subgraph,
                 routing_infos, report_folder=None, hostname=None,
                 router_algorithm=None):
        """
        :param router_algorithm: The router algorithm.  If not specified, a\
                    default algorithm will be used
        :type router_algorithm:\
                    :py:class:`pacman.operations.router_algorithms.abstract_router_algorithm.AbstractRouterAlgorithm`
        :raise pacman.exceptions.PacmanInvalidParameterException: If\
                    router_algorithm is not valid
        """
        self._report_folder = report_folder
        self.report_states = report_states
        self._hostname = hostname
        self._machine = machine
        self._subgraph = subgraph
        self._routing_infos = routing_infos
        self._placements = placements
        self._router_algorithm = router_algorithm

        #set up a default placer algorithum if none are specified
        if self._router_algorithm is None:
            self._router_algorithm =
        else:
            self._router_algorithm =

    def run(self, routing_info_allocation, placements, machine):
        """ Execute the router algorithm, finding the routes through the\
            machine for the given placed subedges
            
        :param routing_info_allocation: The allocated routing information
        :type routing_info_allocation:\
                    :py:class:`pacman.model.routing_info.routing_info.RoutingInfo`
        :param placements: The placements of the subedges
        :type placements:\
                    :py:class:`pacman.model.placements.placements.Placements`
        :param machine: The machine through which the routes are to be found
        :type machine: :py:class:`spinn_machine.machine.Machine`
        :return: The discovered routes 
        :rtype: :py:class:`pacman.model.routing_tables.multicast_routing_tables.MulticastRoutingTables`
        :raise pacman.exceptions.PacmanRoutingException: If something\
                   goes wrong with the routing
        """
        placements = \
            self._router_algorithm.route(subgraph, graph_to_subgraph_mapper)

        #execute reports if needed
        if (self.report_states is not None and
                self.report_states.router_reports):
            reports.router_report(
                graph=self._graph, hostname=self._hostname,
                graph_to_subgraph_mapper=graph_to_subgraph_mapper,
                machine=self._machine, placements=placements,
                report_folder=self._report_folder)

        return placements
