# Copyright 2020 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ops_openstack.core
# ch_context needed for bluestore validation
import charmhelpers.contrib.openstack.context as ch_context
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)


class BaseCephClientCharm(ops_openstack.core.OSBaseCharm):

    def __init__(self, framework):
        super().__init__(framework)
        super().register_status_check(self.check_bluestore_compression)

    def check_bluestore_compression(self):
        try:
            self.get_bluestore_compression()
            return ActiveStatus()
        except ValueError as e:
            return BlockedStatus(
                'Invalid configuration: {}'.format(str(e)))

    @staticmethod
    def get_bluestore_compression():
        """Get BlueStore Compression charm configuration if present.

        :returns: Dictionary of options suitable for passing on as keyword
                  arguments or None.
        :rtype: Optional[Dict[str,any]]
        :raises: ValueError
        """
        try:
            bluestore_compression = (
                ch_context.CephBlueStoreCompressionContext())
            bluestore_compression.validate()
        except KeyError:
            # The charm does not have BlueStore Compression options defined
            bluestore_compression = None
        if bluestore_compression:
            return bluestore_compression.get_kwargs()
