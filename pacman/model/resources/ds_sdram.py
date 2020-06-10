# Copyright (c) 2017-2019 The University of Manchester
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
from .with_malloc_sdram import WithMallocSdram
from spinn_utilities.overrides import overrides
from pacman.utilities.constants import SARK_PER_MALLOC_SDRAM_USAGE


class DsSDRAM(WithMallocSdram):
    """ A resource for SDRAM that comes in DS regions and has malloc costs

        Handles all the regions that are part of the same DS generation phase
        for a single core. Currently malloc cost is only added once as all
        regions are malloced in a single block.

        The malloc cost will be automatically added to the total costs,
        but is not part of any of the regions and reported after a subtotal.

        .. note:
        Adding or Subtracting two MultiRegionSDRAM objects will be assumed to
        be an operation over multiple cores/placements so these functions
        return a VariableSDRAM object without the regions data.

        To add extra SDRAM costs for the same core/placement use the method
        add_cost
        merge (But only of another DsSDRAM)
        nest (But only of a MultiRegionSDRAM without malloc)
    """

    def __init__(self):
        super(DsSDRAM, self).__init__()
        self._fixed_sdram = self.malloc_cost

    @property
    @overrides(WithMallocSdram.malloc_cost)
    def malloc_cost(self):
        """
        The part of total (fixed cost) that was automatically added for malloc
        :return: malloc cost in bytes.
        """
        return SARK_PER_MALLOC_SDRAM_USAGE

    @overrides(WithMallocSdram.merge)
    def merge(self, other):
        super(DsSDRAM, self).merge(other)
        self._fixed_sdram -= self.malloc_cost
