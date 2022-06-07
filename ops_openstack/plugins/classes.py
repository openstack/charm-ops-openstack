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

import json

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


class CinderStoragePluginCharm(ops_openstack.core.OSBaseCharm):

    def __init__(self, framework):
        super().__init__(framework)
        self.framework.observe(
            self.on.storage_backend_relation_changed,
            self.on_storage_backend)

    def render_config(self, config, app_name):
        return json.dumps({
            "cinder": {
                "/etc/cinder/cinder.conf": {
                    "sections": {app_name: self.cinder_configuration(config)}
                }
            }
        })

    def set_data(self, data, config, app_name):
        """Inform another charm of the backend name and configuration."""
        data['backend_name'] = app_name
        data['stateless'] = str(self.stateless)
        data['active_active'] = str(self.active_active)
        data['subordinate_configuration'] = self.render_config(
            config, app_name)

    def on_config(self, event):
        config = dict(self.framework.model.config)
        app_name = self.framework.model.app.name
        for relation in self.framework.model.relations.get('storage-backend'):
            self.set_data(relation.data[self.unit], config, app_name)
        self.unit.status = ActiveStatus('Unit is ready')

    def on_storage_backend(self, event):
        self.set_data(
            event.relation.data[self.unit],
            self.framework.model.config,
            self.framework.model.app.name)

    def cinder_configuration(self, charm_config):
        """Entry point for cinder subordinates.

        This method should return a list of 2-element tuples, where the
        first element is the configuration key, and the second, its value."""

        raise NotImplementedError()

    @property
    def stateless(self):
        """Indicate whether the charm is stateless.

        For more information, see: https://cinderlib.readthedocs.io/en/v0.2.1/topics/serialization.html

        :returns: A boolean value indicating statefulness.
        :rtype: bool
        """   # noqa
        return False

    @property
    def active_active(self):
        """Indicate active-active support in the charm.

        For more information, see: https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/cinder-volume-active-active-support.html

        :returns: A boolean indicating active-active support.
        :rtype: bool
        """   # noqa
        return False
