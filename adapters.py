# Copyright 2016 Canonical Ltd
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

"""Adapter classes and utilities for use with Reactive interfaces"""
from __future__ import absolute_import

from ops.framework import Object


class OpenStackOperRelationAdapter(object):
    """
    Base adapter class for all OpenStack related adapters.
    """

    interface_type = None
    """
    The generic type of the interface the adapter is wrapping.
    """

    def __init__(self, relation):
        """Class will usually be initialised using the 'relation' option to
           pass in an instance of a interface class. If there is no relation
           class yet available then 'relation_name' can be used instead.

           :param relation: Instance of an interface class
           :param accessors: List of accessible interfaces properties
           :param relation_name: String name of relation
        """
        self.relation = relation
        self._setup_properties()

    def _setup_properties(self):
        """
        Setup property based accessors for interface.

        For charms.reactive.Endpoint interfaces a list of properties is built
        by looking for type(property) attributes added by the interface class.

        For charms.reactive.RelationBase interfaces the auto_accessors list is
        used to determine which properties to set.

        Note that the accessor is dynamic as each access calls the underlying
        getattr() for each property access.
        """
        # Get names of properties the interface class instance has,
        # remove the properties inherited from charms.reactive.Endpoint
        # base class
        interface_instance_names = dir(self.relation)
        property_names = [
            p for p in interface_instance_names if isinstance(
                getattr(type(self.relation), p, None), property)]
        for name in property_names:
            # The double lamda trick is necessary to ensure we get fresh
            # data from the interface class property at every call to the
            # new property. Without it we would store the value that was
            # there at instantiation of this class.
            setattr(self.__class__,
                    name,
                    (lambda name: property(
                        lambda self: getattr(
                            self.relation, name)))(name))


class ConfigurationAdapter(object):
    """
    Configuration Adapter which provides python based access
    to all configuration options for the current charm.

    It also holds a weakref to the instance of the OpenStackCharm derived class
    that it is associated with.  This is so that methods on the configuration
    adapter can query the charm class for global config (e.g. service_name).


    The configuration items from Juju are copied over and the '-' are replaced
    with '_'.  This allows them to be used directly on the instance.
    """

    def __init__(self, charm_instance):
        """Create a ConfigurationAdapter (or derived) class.

        :param charm_instance: the instance of the OpenStackCharm derived
            class.
        """
        for k, v in charm_instance.framework.model.config.items():
            k = k.replace('-', '_')
            setattr(self, k, v)


class OpenStackRelationAdapters(Object):
    """
    Base adapters class for OpenStack Charms, used to aggregate
    the relations associated with a particular charm so that their
    properties can be accessed using dot notation, e.g:

        adapters.amqp.private_address
    """

    relation_adapters = {}
    """
    Dictionary mapping relation names to adapter classes, e.g:

        relation_adapters = {
            'amqp': RabbitMQRelationAdapter,
        }

    By default, relations will be wrapped in an OpenStackRelationAdapter.

    Each derived class can define their OWN relation_adapters and they will
    overlay on the class further back in the class hierarchy, according to the
    mro() for the class.
    """

    def __init__(self, relations, charm_instance, options_instance=None):
        """
        :param relations: List of instances of relation classes
        :param options: Configuration class to use (DEPRECATED)
        :param options_instance: Instance of Configuration class to use
        :param charm_instance: optional charm_instance that is captured as a
            weakref for use on the adapter.
        """
        self.charm_instance = charm_instance
        self._relations = set()
        self._adapters = {}
        for cls in reversed(self.__class__.mro()):
            self._adapters.update(
                {k.replace('-', '_'): v
                 for k, v in getattr(cls, 'relation_adapters', {}).items()})
        self.add_relations(relations)
        setattr(self, 'options', ConfigurationAdapter(charm_instance))

    def __iter__(self):
        """
        Iterate over the relations presented to the charm.
        """
        for relation in self._relations:
            yield relation, getattr(self, relation)

    def add_relations(self, relations):
        """Add the relations to this adapters instance for use as a context.

        :params relations: list of RAW reactive relation instances.
        """
        for relation in relations:
            self.add_relation(relation)

    def add_relation(self, relation):
        """Add the relation to this adapters instance for use as a context.

        :param relation: a RAW reactive relation instance
        """
        adapter_name, adapter = self.make_adapter(relation)
        setattr(self, adapter_name, adapter)
        self._relations.add(adapter_name)

    def make_adapter(self, relation):
        """Make an adapter from a reactive relation.
        This returns the relation_name and the adapter instance based on the
        registered custom adapter classes and any customised properties on
        those adapter classes.

        :param relation: a RelationBase derived reactive relation
        :returns (string, OpenstackRelationAdapter-derived): see above.
        """
        try:
            relation_name = relation.endpoint_name.replace('-', '_')
        except AttributeError:
            relation_name = relation.relation_name.replace('-', '_')
        try:
            adapter = self._adapters[relation_name](relation)
        except KeyError:
            adapter = OpenStackOperRelationAdapter(relation)
        return relation_name, adapter
