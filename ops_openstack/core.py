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
}


_releases = {}
logger = logging.getLogger(__name__)


class OSBaseCharm(CharmBase):
    _stored = StoredState()

    PACKAGES = []

    RESTART_MAP = {}

    REQUIRED_RELATIONS = []

    def __init__(self, framework):
        super().__init__(framework)
        self._stored.set_default(is_started=False)
        self._stored.set_default(is_paused=False)
        self._stored.set_default(series_upgrade=False)
        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.update_status, self.on_update_status)
        self.framework.observe(self.on.pause_action, self.on_pause_action)
        self.framework.observe(self.on.resume_action, self.on_resume_action)
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

    def update_status(self):
        logging.info("Updating status")
        try:
            # Custom checks return True if the checked passed else False.
            # If the check failed the custom check will have set the status.
            if not self.custom_status_check():
                return
        except NotImplementedError:
            pass
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
        if self._stored.is_started:
            self.unit.status = ActiveStatus('Unit is ready')
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
