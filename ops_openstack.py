from ops.charm import CharmBase
from ops.framework import (
    StoredState,
)
import ops.model

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
logger = logging.getLogger()


class OSBaseCharm(CharmBase):
    state = StoredState()

    PACKAGES = []

    RESTART_MAP = {}

    REQUIRED_RELATIONS = []

    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.state.set_default(is_started=False)
        self.state.set_default(is_paused=False)
        self.framework.observe(self.on.install, self)
        self.framework.observe(self.on.update_status, self)
        self.framework.observe(self.on.pause_action, self)
        self.framework.observe(self.on.resume_action, self)

    def on_install(self, event):
        logging.info("Installing packages")
        if self.framework.model.config.get('source'):
            add_source(
                self.framework.model.config['source'],
                self.framework.model.config.get('key'))
        apt_update(fatal=True)
        apt_install(self.PACKAGES, fatal=True)
        self.update_status()

    def update_status(self):
        logging.info("Updating status")
        if self.state.is_paused:
            self.model.unit.status = MaintenanceStatus(
                "Paused. Use 'resume' action to resume normal service.")
        missing_relations = []
        for relation in self.REQUIRED_RELATIONS:
            if not self.framework.model.get_relation(relation):
                missing_relations.append(relation)
        if missing_relations:
            self.model.unit.status = BlockedStatus(
                'Missing relations: {}'.format(', '.join(missing_relations)))
            return
        if self.state.is_started:
            self.model.unit.status = ActiveStatus('Unit is ready')
        else:
            self.model.unit.status = WaitingStatus('Not ready for reasons')
        logging.info("Status updated")

    def on_update_status(self, event):
        self.update_status()

    def services(self):
        _svcs = []
        for svc in self.RESTART_MAP.values():
            _svcs.extend(svc)
        return list(set(_svcs))

    def on_pause_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'pause',
            services=self.services(),
            charm_func=None)
        self.state.is_paused = True
        self.update_status()

    def on_resume_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'resume',
            services=self.services(),
            charm_func=None)
        self.state.is_paused = False
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
    current_model = ops.model.ModelBackend()
    config = current_model.config_get()
    if 'source' in config:
        _origin = config['source']
    elif 'openstack-origin' in config:
        _origin = config['openstack-origin']
    else:
        _origin = 'distro'
    # XXX Make this support openstack and ceph
    target_release = os_utils.get_os_codename_install_source(_origin)
    # Check for a cepch charm match first:
    ceph_release = UCA_CODENAME_MAP[target_release]
    releases = sorted(list(set(UCA_CODENAME_MAP.values())))
    return get_charm_class(release=ceph_release, all_releases=releases)
