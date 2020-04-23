#!/usr/bin/env python3

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

from mock import patch, MagicMock

from ops.testing import Harness
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    WaitingStatus,
)

import ops_openstack


class OpenStackTestAPICharm(ops_openstack.OSBaseCharm):

    PACKAGES = ['keystone-common']
    REQUIRED_RELATIONS = ['shared-db']
    RESTART_MAP = {
        '/etc/f1.conf': ['apache2'],
        '/etc/f2.conf': ['apache2', 'ks-api'],
        '/etc/f3.conf': []}

    def custom_status_check(self):
        if self.model.config.get('custom-check-fail', 'False') == 'True':
            self.unit.status = MaintenanceStatus(
                'Custom check failed')
            return False
        else:
            return True


class CharmTestCase(unittest.TestCase):

    def setUp(self, obj, patches):
        super(CharmTestCase, self).setUp()
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


class TestOSBaseCharm(CharmTestCase):

    PATCHES = [
        'add_source',
        'apt_update',
        'apt_install',
        'os_utils']

    def setUp(self):
        super(TestOSBaseCharm, self).setUp(ops_openstack, self.PATCHES)
        self.os_utils.manage_payload_services = MagicMock()
        self.harness = Harness(
            OpenStackTestAPICharm,
            meta='''
                name: client
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

    def test_init(self):
        self.harness.begin()
        self.assertFalse(self.harness.charm.state.is_started)
        self.assertFalse(self.harness.charm.state.is_paused)
        self.assertFalse(self.harness.charm.state.series_upgrade)
        events = list(self.harness.charm.on.events())
        self.assertEqual(
            sorted(events),
            [
                'ceph_client_relation_broken',
                'ceph_client_relation_changed',
                'ceph_client_relation_departed',
                'ceph_client_relation_joined',
                'collect_metrics',
                'config_changed',
                'install',
                'leader_elected',
                'leader_settings_changed',
                'pause_action',
                'post_series_upgrade',
                'pre_series_upgrade',
                'remove',
                'resume_action',
                'start',
                'stop',
                'update_status',
                'upgrade_charm'])

    def test_install(self):
        self.harness.begin()
        self.harness.charm.on_install('An Event')
        self.assertFalse(self.add_source.called)
        self.apt_update.assert_called_once_with(fatal=True)
        self.apt_install.assert_called_once_with(
            ['keystone-common'],
            fatal=True)

    def test_install_ppa(self):
        self.harness.update_config(
            key_values={
                'source': 'cloud:myppa',
                'key': 'akey'})
        self.harness.begin()
        self.harness.charm.on_install('An Event')
        self.add_source.assert_called_once_with('cloud:myppa', 'akey')
        self.apt_update.assert_called_once_with(fatal=True)
        self.apt_install.assert_called_once_with(
            ['keystone-common'],
            fatal=True)

    def test_update_status(self):
        self.harness.add_relation('shared-db', 'mysql')
        self.harness.begin()
        self.harness.charm.state.is_started = True
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Unit is ready')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            ActiveStatus)

    def test_update_status_custom_check_fail(self):
        self.harness.update_config(
            key_values={
                'custom-check-fail': 'True'})
        self.harness.add_relation('shared-db', 'mysql')
        self.harness.begin()
        self.harness.charm.state.is_started = True
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Custom check failed')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            MaintenanceStatus)

    def test_update_status_not_started(self):
        self.harness.add_relation('shared-db', 'mysql')
        self.harness.begin()
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Charm configuration in progress')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            WaitingStatus)

    def test_update_status_series_upgrade(self):
        self.harness.begin()
        self.harness.charm.state.series_upgrade = True
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            ('Ready for do-release-upgrade and reboot. Set complete when '
             'finished.'))
        self.assertIsInstance(
            self.harness.charm.unit.status,
            BlockedStatus)

    def test_update_status_series_paused(self):
        self.harness.begin()
        self.harness.charm.state.is_paused = True
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            "Paused. Use 'resume' action to resume normal service.")
        self.assertIsInstance(
            self.harness.charm.unit.status,
            MaintenanceStatus)

    def test_update_status_missing_relation(self):
        self.harness.begin()
        self.harness.charm.on_update_status('An Event')
        self.assertEqual(
            self.harness.charm.unit.status.message,
            'Missing relations: shared-db')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            BlockedStatus)

    def test_services(self):
        self.harness.begin()
        self.assertEqual(
            self.harness.charm.services(),
            ['apache2', 'ks-api'])

    def test_pre_series_upgrade(self):
        self.os_utils.manage_payload_services.return_value = ('a', 'b')
        self.harness.begin()
        self.assertFalse(self.harness.charm.state.series_upgrade)
        self.assertFalse(self.harness.charm.state.is_paused)
        self.harness.charm.on_pre_series_upgrade('An Event')
        self.assertTrue(self.harness.charm.state.series_upgrade)
        self.assertTrue(self.harness.charm.state.is_paused)
        self.os_utils.manage_payload_services.assert_called_once_with(
            'pause',
            services=['apache2', 'ks-api'],
            charm_func=None)

    def test_post_series_upgrade(self):
        self.os_utils.manage_payload_services.return_value = ('a', 'b')
        self.harness.begin()
        self.harness.charm.state.series_upgrade = True
        self.harness.charm.state.is_paused = True
        self.harness.charm.on_post_series_upgrade('An Event')
        self.assertFalse(self.harness.charm.state.series_upgrade)
        self.assertFalse(self.harness.charm.state.is_paused)
        self.os_utils.manage_payload_services.assert_called_once_with(
            'resume',
            services=['apache2', 'ks-api'],
            charm_func=None)

    def test_pause(self):
        self.os_utils.manage_payload_services.return_value = ('a', 'b')
        self.harness.begin()
        self.assertFalse(self.harness.charm.state.is_paused)
        self.harness.charm.on_pause_action('An Event')
        self.assertTrue(self.harness.charm.state.is_paused)
        self.os_utils.manage_payload_services.assert_called_once_with(
            'pause',
            services=['apache2', 'ks-api'],
            charm_func=None)

    def test_resume(self):
        self.os_utils.manage_payload_services.return_value = ('a', 'b')
        self.harness.begin()
        self.harness.charm.state.is_paused = True
        self.harness.charm.on_resume_action('An Event')
        self.assertFalse(self.harness.charm.state.is_paused)
        self.os_utils.manage_payload_services.assert_called_once_with(
            'resume',
            services=['apache2', 'ks-api'],
            charm_func=None)
