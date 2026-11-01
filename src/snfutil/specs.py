"""
Specification classes for Synnefo resources.

These classes define the specifications for servers, 
networks, and clusters in a Synnefo cloud environment.
"""

from __future__ import annotations
import os
import pathlib
from typing import Any
from abc import ABC, abstractmethod
import typing
import yaml
from .core import options_to_args, SnfObject
from .kamaki_run import entity_info, resolve_entity, all_entities


class ServerSpec:
    """
    Specification of a server.

    Parameters
    ----------
    name: str
        Name of the server
    project: SnfObject
        The project info
    flavor: SnfObject
        The flavor object
    image: SnfObject
        The image object
    key: tr (=None)
        The name of the SSH key to use
    networks: []
        Pair (netid, addr), where addr must be a floating ip or None
    status:
        The goal status, e.g.  'ACTIVE' or None    
    """
    def __init__(self, name, project, flavor, image,
                 key=None, networks=[], volumes=[], status=None):
        self.name = name
        self.project = project
        self.flavor = flavor
        self.image = image
        # Add the required attributes to the options
        self.options = {
            'name': self.name,
            'project-id': self.project.id,
            'flavor-id': self.flavor.id,
            'image-id': self.image.id,
        }

        self.key = self.add_key(key)
        self.networks = []
        for net_addr in networks:
            self.add_network(net_addr[0], net_addr[1])

        self.volumes = []
        for vol in volumes:
            self.add_volume(vol.name, vol.size)

        self.status = None
        self.set_status(status)

    @classmethod
    def from_server(cls, srv_id):
        srv = entity_info('server', srv_id)
        project = resolve_entity('project', srv.tenant_id)
        flavor = resolve_entity('flavor', srv.flavor['id'])
        image = resolve_entity('image', srv.image['id'])
        spec = cls(srv.name, project, flavor, image)

        # Add optional key spec
        try:
            spec.add_key(srv.key_name)
        except AttributeError:
            pass

        # Add network specs
        for nw in srv.addresses:
            nwspec = srv.addresses[nw]
            for addr in nwspec:
                if addr['version'] == 6:
                    continue
                elif addr['OS-EXT-IPS:type'] == 'fixed':
                    spec.add_network(nw)
                elif addr['OS-EXT-IPS:type'] == 'floating':
                    spec.add_network(nw, addr['addr'])
                
        # Remember, this is the **goal**
        if srv.status in ('ACTIVE', 'BUILD', 'ERROR'):
            spec.set_status('ACTIVE')
        else:
            spec.set_status(None)

        return spec

    def add_key(self, key_name):
        self.key = key_name
        if key_name is not None:
            self.options['key-name'] = key_name

    def _add_network_to_options(self, netid, ipaddr=None):
        if 'network' not in self.options:
            self.options['network'] = []
        if ipaddr is not None:
            netspec = f"id={netid},ip={ipaddr}"
        else:
            netspec = f"id={netid}"
        self.options['network'].append(netspec)

    def add_network(self, netid, ipaddr=None):
        self._add_network_to_options(netid, ipaddr)
        self.networks.append((netid, ipaddr))

    def add_volume(self, volgroup_name, vol_size):
        vol_name = f"{volgroup_name}_{self.name}"
        self.volumes.append((vol_name, vol_size))

    def set_status(self, new_status):
        if new_status not in ('ACTIVE', 'DELETED', None):
            raise ValueError(f"Expected goal status, got {new_status}")
        self.status = new_status

    def command(self):
        """
        Return a sequence of strings that can be used with kamaki().
        """
        cmd = ['server', 'create', * options_to_args(self.options)]
        return cmd

    def __repr__(self):
        return f"ServerSpec<{' '.join(self.command())}>"

    def __str__(self):
        return f"kamaki {' '.join(self.command())}"


class NetworkSpec(ABC):
    @abstractmethod
    def add_to_server_spec(self, spec, n):
        pass

    @abstractmethod
    def make(self):
        pass


class NetworkPrivate(NetworkSpec):
    def __init__(self, network, cluster_spec):
        self.network = network
        self.cluster_spec = cluster_spec
        if self.network['SNF:floating_ip_pool']:
            raise ValueError(f"Network {self.network.name} "
                             "is a floating IP network")

    def add_to_server_spec(self, spec, n):
        spec.add_network(self.network.id)

    def make(self):
        pass


class NetworkPublic(NetworkSpec):
    def __init__(self, network, cluster_spec, **kwargs):
        self.network = network
        self.cluster_spec = cluster_spec
        if not self.network['SNF:floating_ip_pool']:
            raise ValueError(f"Network {self.network.name}"
                             " is not floating IP network")

    def allocate_ip(self):
        """Generate an array of IP addresses for the servers of the cluster
        """
        proj_id = self.cluster_spec.project.id
        netw_id = self.network.id
        server_names = self.cluster_spec.server_names()

        ipaddr = [None] * self.cluster_spec.num_nodes

        # First, take care to preserve IPs already allocated
        def in_cluster(srv):
            return (srv.tenant_id == proj_id and
                    srv.name in server_names)
        srv = all_entities('server', in_cluster, details=True)

        for server in srv:
            i = server_names.index(server.name)
            if netw_id in server.addresses:                
                ipaddr[i] = server.addresses[netw_id][0]['addr']
                        
    
        # Νow, find unused IPs for the remaining nodes, if any
        def filt(a):
            return (a.tenant_id == proj_id
                    and a.floating_network_id == netw_id
                    and a.instance_id is None)
        
        free_ips = list(a.floating_ip_address 
                        for a in all_entities('ip', where=filt))
        needed_ips = sum(1 for a in ipaddr if a is None)

        if needed_ips > len(free_ips):
            raise RuntimeError(f"Network {netw_id} needs {needed_ips} free IPs"
                               f" but only {len(free_ips)} are available")
        
        free_ips.sort(reverse=True)
        for i, _ in enumerate(ipaddr):
            if ipaddr[i] is None:
                addr = free_ips.pop()
                ipaddr[i] = addr

        return ipaddr

    def make(self):
        if hasattr(self, 'ipaddr'):
            return self.ipaddr
        fip = self.allocate_ip()
        return self.init_ipaddr(fip)
    
    def init_ipaddr(self, fip):
        if len(fip) < self.cluster_spec.num_nodes:
            raise ValueError(f"There are only {len(fip)} available IPs, "
                             f"{self.cluster_spec.num_nodes} are needed.")

        self.ipaddr = fip[:self.cluster_spec.num_nodes]
        return self.ipaddr

    def add_to_server_spec(self, spec, n):
        ipaddr = self.ipaddr[n]
        spec.add_network(self.network.id, ipaddr=ipaddr)


class VolumeSpec:
    def __init__(self, cluster_spec, name, size, servers=None):
        self.cluster_spec = cluster_spec
        self.name = name

        srv_names = set( cluster_spec.server_names() )

        # Size and servers combine to create the size map
        if not isinstance(size, dict):
            if servers is None:
                servers = cluster_spec.server_names()
            size = {s: size for s in servers}

        # Validate the size map
        if not all(s in srv_names for s in size):
            bad_names = [s for s in size if s not in srv_names]
            raise ValueError(f"Bad server names in volume spec: {bad_names}")
        
        if any(sz <= 0 for sz in size.values()):
            raise ValueError("Non-positive sizes requested")

        self.size = size

    def total_size(self):
        return sum(self.size.values())

    def add_to_server_spec(self, spec, n):
        if spec.name in self.size:
            sz = self.size[spec.name]
            spec.add_volume(self.name, sz)

    def make(self):
        pass


class ClusterSpec:
    """
    Specification for a cluster of similar servers.

    This class represents the specification for a collection of similar
    servers that are intended to be part of the same cluster, sharing
    common characteristics such as flavor, image, and network configuration.

    The specification includes details such as the number of nodes, the project,
    flavor, image, networks, volumes, and other configuration options that define
    the desired state of the cluster.

    This information can be used to allocate the cluster VMs and provision them
    with the specified configuration and resources. In addition, this specification
    can serve as an ansible inventory source for automation purposes.
    """
    def __init__(self, 
                 num_nodes: int,
                 project: Any, flavor: Any, image: Any,
                 name=None,
                 key=None,
                 networks=[],
                 volumes=[],
                 init_num=1, 
                 name_pattern='server%02d',
                 status='ACTIVE',
                 hostvars=None,
                 inventory=None,
                 plugin = None,     # option is ignored
                 **kwargs):
        """
        Collect the data needed to create a set of nodes with similar setup.

        Parameters
        ----------
        num_nodes: int
            Number of nodes to create
        project:
            Name or id of tje project whose resources will be used.
        flavor:
            Name or id of the flavor of the machine to build.
        image:
            Name or id of the image used.
        key (=None):
            Name of keypair used to initialize the machines.
        networks (=[]):
            A name or a list of names for networks to use.
            For a public IP network (with floating ip addesses),
            an IP address will be assigned explicity.
            For a private network we rely on automatic assignment.
        volumes (=[]):
            An array of VolumeSpec, for extra volumes attached to servers.
        init_num (=1): int
            The number of the first node. See name_pattern.
        name_pattern (="kube%02d"):
            Nodes will be contstucted for every i in
            range(init_num, init_num+num_nodes), and node i will
            be named by expression `name_pattern % i`
        status (=None): in ('ACTIVE', 'DELETED', None)
            The status goal for every node
        
        The following parameters are used by Ansible
        hostvars = None: dict
            A description of 
        inventory = None: dict
        """
        super().__init__(**kwargs)
        self.project = resolve_entity('project', project, details=True)
        self.flavor = resolve_entity('flavor', flavor, details=True)
        self.image = resolve_entity('image', image, details=True)

        # Control the node number and naming
        self.num_nodes = num_nodes
        self.init_num = init_num
        self.name_pattern = name_pattern

        # Optional item: key pair
        self.key = resolve_entity('keypair', key, optional=True)

        # Goal status for all nodes
        self.status = status

        # Ansible inventory data
        self.hostvars = hostvars
        self.inventory = inventory

        # Set a name for this cluster spec
        self.name = name
        self.yaml_path = None

        # Optional item: network
        if not isinstance(networks, (list, tuple)):
            networks = [networks]

        self.networks = [
            self.create_network_profile(nw)
            for nw in networks
        ]

        self.volumes = [
            VolumeSpec(self, **vol)
            for vol in volumes
        ]

    @classmethod
    def from_file(cls, fobj: typing.TextIO, name=None) -> ClusterSpec:
        """Create cluster spec for open file-like object, without closing"""
        spargs = yaml.safe_load(fobj)
        spec = cls(**spargs)
        if name is not None:
            spec.name = name
        return spec

    @classmethod
    def from_yaml_file(cls, yaml_path: os.PathLike) -> ClusterSpec:
        with open(yaml_path) as f:
            cspec = cls.from_file(f)
            cspec.yaml_path = pathlib.Path(yaml_path)
            if cspec.name is None:
                cspec.name = cspec.yaml_path.stem
            return cspec

    @classmethod
    def from_yaml_text(cls, yaml_spec, name=None):
        import io
        with io.StringIO(yaml_spec) as f:
            return cls.from_file(f, name=name)

    def spec_ident(self):
        if self.name is not None:
            return str(self.name)
        ident = f"{self.project.name}-{self.node_name(0)}-{self.node_name(self.num_nodes-1)}"
        return ident

    def __repr__(self):
        return f"ClusterSpec({self.spec_ident()})"

    def add_key(self, key_name):
        self.key = resolve_entity('keypair', key_name)

    def node_no(self, i):
        """Return the numbering of node i, where 0 <= i < self.num_nodes
        
            This is just self.init_num+i
        """
        return self.init_num+i

    def node_name(self, i):
        """Return the name of node i, where 0 <= i < self.num_nodes.
        """
        return self.name_pattern % self.node_no(i)

    def create_network_profile(self, netw):
        if isinstance(netw, (dict, SnfObject)):
            nwsel = SnfObject(netw) / ['ipaddr']  # Do not match on ipaddr
        else:
            nwsel = netw
        
        network = resolve_entity('network', nwsel, info=True)
        if network.public:
            # Public network
            netpub = NetworkPublic(network, self)

            # If given, initialize public network with list of IPs.
            # This must be passed as an array of strings under attribute
            # 'ipaddr'
            if isinstance(netw, (SnfObject, dict)):
                if 'ipaddr' in netw:
                    netpub.init_ipaddr(netw['ipaddr'])
            return netpub

        else:
            # Private networks always get assigned IPs automatically.
            return NetworkPrivate(network, self)

    def make_spec(self, n):
        node_name = self.node_name(n)
        spec = ServerSpec(node_name, self.project, self.flavor, self.image)

        # Add key pair is specified
        if self.key is not None:
            spec.add_key(self.key.name)

        # Add options for each network
        for nw in self.networks:
            nw.add_to_server_spec(spec, n)

        # Add volume specs
        for vol in self.volumes:
            vol.add_to_server_spec(spec, n)

        # Set the status
        spec.set_status(self.status)

        return spec

    def make(self):
        if hasattr(self, 'specs'):
            return self.specs

        # Prepare networks
        for nw in self.networks:
            nw.make()

        # Prepare volumes
        for vol in self.volumes:
            vol.make()

        # Create the specs
        self.specs = [
            self.make_spec(n)
            for n in range(self.num_nodes)
        ]

        return self.specs

    def server_names(self):
        return [self.node_name(i) for i in range(self.num_nodes)]

