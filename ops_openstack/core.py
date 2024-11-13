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

from ops.charm import CharmBase
from ops.framework import (
    StoredState,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    add_source,
)
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    WaitingStatus,
)
import charmhelpers.core.hookenv as hookenv
import charmhelpers.contrib.openstack.utils as os_utils
import logging

# Stolen from charms.ceph
UCA_CODENAME_MAP = {
    'icehouse': 'firefly',
    'juno': 'firefly',
    'kilo': 'hammer',
    'liberty': 'hammer',
    'mitaka': 'jewel',
    'newton': 'jewel',
    'ocata': 'jewel',
    'pike': 'luminous',
    'queens': 'luminous',
    'rocky': 'mimic',
    'stein': 'mimic',
    'train': 'nautilus',
    'ussuri': 'octopus',
    'victoria': 'octopus',
    'wallaby': 'pacific',
    'xena': 'pacific',
    'yoga': 'quincy',
    'zed': 'quincy',
    'antelope': 'quincy',
    'bobcat': 'reef',
    'caracal': 'squid',
    'dalmatian': 'squid',
    'epoxy': 'squid',
}


_releases = {}
logger = logging.getLogger(__name__)


class OSBaseCharm(CharmBase):
    _stored = StoredState()

    PACKAGES = []

    RESTART_MAP = {}

    REQUIRED_RELATIONS = []

    MANDATORY_CONFIG = []

    def __init__(self, framework):
        super().__init__(framework)
        self.custom_status_checks = []
        self._stored.set_default(is_started=False)
        self._stored.set_default(is_paused=False)
        self._stored.set_default(series_upgrade=False)
        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.update_status, self.on_update_status)
        self.framework.observe(self.on.config_changed, self._on_config)
        # A charm may not have pause/resume actions if it does not manage a
        # daemon.
        try:
            self.framework.observe(
                self.on.pause_action,
                self.on_pause_action)
        except AttributeError:
            pass
        try:
            self.framework.observe(
                self.on.resume_action,
                self.on_resume_action)
        except AttributeError:
            pass
        self.framework.observe(self.on.pre_series_upgrade,
                               self.on_pre_series_upgrade)
        self.framework.observe(self.on.post_series_upgrade,
                               self.on_post_series_upgrade)

    def install_pkgs(self):
        logging.info("Installing packages")
        if self.model.config.get('source'):
            add_source(
                self.model.config['source'],
                self.model.config.get('key'))
        apt_update(fatal=True)
        apt_install(self.PACKAGES, fatal=True)
        self.update_status()

    def on_install(self, event):
        self.install_pkgs()

    def custom_status_check(self):
        raise NotImplementedError

    def register_status_check(self, custom_check):
        self.custom_status_checks.append(custom_check)

    def update_status(self):
        """Update the charms status

        A charm, or plugin, can register checks to be run when calculating the
        charms status. Each status method should have a unique name. The custom
        check should return a StatusBase object.  If the check returns an
        ActiveStatus object then subsequent checks are run, if it returns
        anything else then the charms status is set to the object the check
        returned and no subsequent checks are run. If the check returns an
        ActiveStatus with a specific message then this message will be
        concatenated with the other active status messages.

        Example::

        class MyCharm(OSBaseCharm):

            def __init__(self, framework):
                super().__init__(framework)
                super().register_status_check(self.mycharm_check)

            def mycharm_check(self):
                if self.model.config['plugin-check-fail'] == 'True':
                    return BlockedStatus(
                        'Plugin Custom check failed')
                else:
                    return ActiveStatus()

        """
        logging.info("Updating status")
        active_messages = ['Unit is ready']
        for check in self.custom_status_checks:
            _result = check()
            if isinstance(_result, ActiveStatus):
                if _result.message:
                    active_messages.append(_result.message)
            else:
                self.unit.status = _result
                return

        if self._stored.series_upgrade:
            self.unit.status = BlockedStatus(
                'Ready for do-release-upgrade and reboot. '
                'Set complete when finished.')
            return

        if self._stored.is_paused:
            self.unit.status = MaintenanceStatus(
                "Paused. Use 'resume' action to resume normal service.")
            return

        missing_relations = []
        for relation in self.REQUIRED_RELATIONS:
            if not self.model.get_relation(relation):
                missing_relations.append(relation)
        if missing_relations:
            self.unit.status = BlockedStatus(
                'Missing relations: {}'.format(', '.join(missing_relations)))
            return

        _, services_not_running_msg = os_utils.ows_check_services_running(
            self.services(), ports=[])
        if services_not_running_msg is not None:
            self.unit.status = BlockedStatus(services_not_running_msg)
            return

        if self._stored.is_started:
            _unique = []
            # Reverse sort the list so that a shorter message that has the same
            # start as a longer message comes first and can then be omitted.
            # eg 'Unit is ready' comes after 'Unit is ready and clustered'
            # and 'Unit is ready' is dropped.
            for msg in sorted(list(set(active_messages)), reverse=True):
                dupes = [m for m in _unique if m.startswith(msg)]
                if not dupes:
                    _unique.append(msg)
            self.unit.status = ActiveStatus(', '.join(_unique))
        else:
            self.unit.status = WaitingStatus('Charm configuration in progress')

        logging.info("Status updated")

    def on_update_status(self, event):
        self.update_status()

    def services(self):
        _svcs = []
        for svc in self.RESTART_MAP.values():
            _svcs.extend(svc)
        return list(set(_svcs))

    def on_pre_series_upgrade(self, event):
        _, messages = os_utils.manage_payload_services(
            'pause',
            services=self.services(),
            charm_func=None)
        self._stored.is_paused = True
        self._stored.series_upgrade = True
        self.update_status()

    def on_post_series_upgrade(self, event):
        _, messages = os_utils.manage_payload_services(
            'resume',
            services=self.services(),
            charm_func=None)
        self._stored.is_paused = False
        self._stored.series_upgrade = False
        self.update_status()

    def on_pause_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'pause',
            services=self.services(),
            charm_func=None)
        self._stored.is_paused = True
        self.update_status()

    def on_resume_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'resume',
            services=self.services(),
            charm_func=None)
        self._stored.is_paused = False
        self.update_status()

    def on_config(self, event):
        """Main entry point for configuration changes."""
        pass

    def _on_config(self, event):
        missing = []
        config = self.framework.model.config
        for param in self.MANDATORY_CONFIG:
            if param not in config:
                missing.append(param)
        if missing:
            self.unit.status = BlockedStatus(
                'Missing option(s): ' + ','.join(missing))
            return
        self.on_config(event)


def charm_class(cls):
    _releases[cls.release] = {'deb': cls}


# Adapted from charms_openstack.charm.core
def get_charm_class(release=None, package_type='deb', all_releases=None,
                    *args, **kwargs):
    """Get an instance of the charm based on the release (or use the
    default if release is None).

    OS releases are in alphabetical order, so it looks for the first release
    that is provided if release is None, otherwise it finds the release that is
    before or equal to the release passed.

    Note that it passes args and kwargs to the class __init__() method.

    :param release: lc string representing release wanted.
    :param package_type: string representing the package type required
    :returns: BaseOpenStackCharm() derived class according to cls.releases
    """
    if not all_releases:
        all_releases = os_utils.OPENSTACK_RELEASES
    if len(_releases.keys()) == 0:
        raise RuntimeError(
            "No derived BaseOpenStackCharm() classes registered")
    # Note that this relies on OS releases being in alphabetical order
    known_releases = sorted(_releases.keys())
    cls = None
    if release is None:
        # take the latest version of the charm if no release is passed.
        cls = _releases[known_releases[-1]][package_type]
    else:
        # check that the release is a valid release
        if release not in all_releases:
            raise RuntimeError(
                "Release {} is not a known OpenStack release?".format(release))
        release_index = all_releases.index(release)
        if (release_index <
                all_releases.index(known_releases[0])):
            raise RuntimeError(
                "Release {} is not supported by this charm. Earliest support "
                "is {} release".format(release, known_releases[0]))
        else:
            # try to find the release that is supported.
            for known_release in reversed(known_releases):
                if (release_index >=
                        all_releases.index(known_release) and
                        package_type in _releases[known_release]):
                    cls = _releases[known_release][package_type]
                    break
    if cls is None:
        raise RuntimeError("Release {} is not supported".format(release))
    return cls


# Adapted from charms_openstack.charm.core
def get_charm_instance(release=None, package_type='deb', all_releases=None,
                       *args, **kwargs):
    return get_charm_class(
        release=release,
        package_type=package_type,
        all_releases=all_releases,
        *args, **kwargs)(release=release, *args, **kwargs)


def get_charm_class_for_release():
    _origin = None
    # There is no charm class to interact with the ops framework yet
    # and it is now forbidden to access ops.model._Model so fallback
    # to charmhelpers.core.hookenv
    config = hookenv.config()
    if 'source' in config:
        _origin = config['source']
    elif 'openstack-origin' in config:
        _origin = config['openstack-origin']
    if not _origin:
        _origin = 'distro'
    # XXX Make this support openstack and ceph
    target_release = os_utils.get_os_codename_install_source(_origin)
    # Check for a cepch charm match first:
    ceph_release = UCA_CODENAME_MAP[target_release]
    releases = sorted(list(set(UCA_CODENAME_MAP.values())))
    return get_charm_class(release=ceph_release, all_releases=releases)
