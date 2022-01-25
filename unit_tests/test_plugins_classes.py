# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from mock import patch

from ops.testing import Harness
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)

import ops_openstack.plugins.classes


class CephTestCharm(ops_openstack.plugins.classes.BaseCephClientCharm):
    pass


class CharmTestCase(unittest.TestCase):

    def setUp(self, obj, patches):
        super().setUp()
        self.patches = patches
        self.obj = obj
        self.patch_all()

    def patch(self, method):
        _m = patch.object(self.obj, method)
        mock = _m.start()
        self.addCleanup(_m.stop)
        return mock

    def patch_all(self):
        for method in self.patches:
            setattr(self, method, self.patch(method))


class TestBaseCephClientCharm(CharmTestCase):

    PATCHES = [
        'ch_context']

    def setUp(self):
        super().setUp(ops_openstack.plugins.classes, self.PATCHES)
        self.harness = Harness(
            CephTestCharm,
            meta='''
                name: client
                requires:
                  shared-db:
                    interface: mysql-shared
                provides:
                  ceph-client:
                    interface: ceph-client
            ''',
            actions='''
                pause:
                    description: pause action
                resume:
                    description: resume action
            ''')
        self.harness.add_relation('shared-db', 'mysql')

    def test_update_status(self):
        self.harness.begin()
        self.harness.charm._stored.is_started = True
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Unit is ready')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            ActiveStatus)

    def test_update_status_invalid_config(self):

        class BlueCtxt():

            def validate(self):
                raise ValueError('BadKey')

        self.ch_context.CephBlueStoreCompressionContext = BlueCtxt

        self.harness.begin()
        self.harness.charm._stored.is_started = True
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Invalid configuration: BadKey')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            BlockedStatus)


class CinderCharm(ops_openstack.plugins.classes.CinderStoragePluginCharm):

    def cinder_configuration(self, cinder_config):
        return [('volume_driver', 'my-driver'),
                ('some-config', 'some-value')]


class TestBaseCinderCharm(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(
            CinderCharm,
            meta='''
            name: cinder-test
            provides:
                storage-backend:
                    interface: cinder-backend
                    scope: container
            requires:
                juju-info:
                    interface: juju-info
                    scope: container
            '''
        )
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_leader(True)
        backend = self.harness.add_relation('storage-backend', 'cinder')
        self.harness.add_relation_unit(backend, 'cinder/0')

    def test_cinder_base(self):
        self.assertEqual(self.harness.framework.model.app.name, 'cinder-test')
        self.harness.update_config({})
        self.assertTrue(isinstance(self.harness.model.unit.status,
                                   ActiveStatus))
        config = self.harness.charm.cinder_configuration({})
        self.assertTrue(config[0], ('volume_driver', 'my-driver'))
        self.assertTrue(config[1], ('some-config', 'some-value'))
