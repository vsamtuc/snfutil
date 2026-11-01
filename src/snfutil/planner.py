from __future__ import annotations
import sys
from typing import TYPE_CHECKING
from .kamaki_run import resolve_entity, kamaki, all_entities

if TYPE_CHECKING:
    from snfutil.core import SnfObject

RESOURCES=[
    'disk', 'vm', 'floating_ip', 'ram', 'diskspace', 'cpu', 'network', 'pending_app'
]

RESOURCE_UNIT = {
    # None means 'pieces'

    'disk': 'bytes', 
    'vm': None, 
    'floating_ip': None, 
    'ram': 'bytes', 
    'diskspace': 'bytes', 
    'cpu': None, 
    'network': None, 
    'pending_app': None
}

SNF_RESOURCES = [
    'cyclades.disk',
    'cyclades.vm',
    'cyclades.floating_ip',
    'cyclades.ram',
    'pithos.diskspace',
    'cyclades.cpu',
    'cyclades.network.private',
    'astakos.pending_app'
]

RESOURCE_MAP = {
    'cyclades.disk': 'disk',
    'cyclades.vm': 'vm',
    'cyclades.floating_ip': 'floating_ip',
    'cyclades.ram': 'ram',
    'pithos.diskspace': 'diskspace',
    'cyclades.cpu': 'cpu',
    'cyclades.network.private': 'network',
    'astakos.pending_app': 'pending_app'
    }

RESOURCE_RMAP = {v: k for k,v in RESOURCE_MAP.items() }

def resolve_resource(rtype):
    if rtype in RESOURCE_MAP:
        rtype = RESOURCE_MAP[rtype]
    elif rtype not in RESOURCE_MAP.values():
        raise ValueError(f"Resource type {rtype} is unknown")
    return rtype

_QATTR=['limit', 'usage']
QATTR = [*_QATTR, *[f"project_{a}" for a in _QATTR]]

class Quota:
    """
    Quota class representing the quota for a specific resource.

    Attributes
    ----------
    rtype: str
        The type of the resource.
    limit: int
        The quota limit for the resource.
    usage: int
        The current usage of the resource.
    project_limit: int
        The project-wide quota limit for the resource.
    project_usage: int
        The current project-wide usage of the resource.
    """
    def __init__(self, rtype, data):
        self.rtype = resolve_resource(rtype)
        for k,v in data.items():
            setattr(self, k, v)

    @property
    def unit(self):
        """
        Return the unit of the resource.
        """
        return RESOURCE_UNIT[self.rtype]

    def __repr__(self):
        dump_attr = lambda a: self.qty(getattr(self, a))
        all_attr = ', '.join([f"{a}={dump_attr(a)}" for a in QATTR])
        return f"Quota('{self.rtype}', available={self.qty(self.available)}, {all_attr})"

    def uqty(self, m):
        """
        Return the quantity of the resource in its unit, without the unit label.
        """
        if self.unit == 'bytes':
            return f"{float(m)/(1<<30)}"
        else:
            return m

    def qty(self, m):
        if self.unit == 'bytes':
            return f"{float(m)/(1<<30)} GiB"
        else:
            return m

    @property
    def avail_GiB(self):
        if self.unit == 'bytes':
            return self.available / (1<<30)
        else:
            raise TypeError(f"The units of this resource are not 'bytes'")

    @property
    def available(self):
        avail = self.limit - self.usage
        project_avail = self.project_limit - self.project_usage
        return min(avail, project_avail)


class Planner:
    """
    Planner class to examine project quotas and resources.

    A Planner is initialized with a project specification and provides methods 
    to examine its quotas and resources.
    """

    def __init__(self, project_spec):
        self.project = resolve_entity('project', project_spec)

    def quota(self, resource=None):
        """
        Retrieve the quota for the specified resource or all resources if none is specified.
        
        Parameters
        ----------
        resource:
            The resource type to retrieve the quota for. If None, retrieves all resources.

        Returns
        -------
        Quota or list of Quota
            The quota for the specified resource, or a list of quotas for all resources if no resource is specified.
        """

        if resource is None:
            q = kamaki('quota', 'list', project_id=self.project.id)
            return [Quota(rtype, rval) 
                    for rtype, rval in q[self.project.id].items()
                    if rtype != 'astakos.pending_app']
        else:
            if resource not in SNF_RESOURCES:
                res = RESOURCE_RMAP[resource]
            else:
                res = resource
            q = kamaki('quota', 'list', project_id=self.project.id, resource=res)
            return [Quota(rtype, rval) for rtype, rval in q[self.project.id].items()][0]

    def __repr__(self):
        return f"Planner({self.project.name})"

    def floating_ips(self, netid):
        """
        List floating IPs associated with the project and a specific network.

        Parameters
        ----------
        netid:
            The ID of the network to filter floating IPs by.
        """
        netid = str(netid)
        addr = all_entities('ip', where= lambda i: (i.tenant_id == self.project.id and 
                                                     i.floating_network_id==netid))
        # Two indexed collections
        servers = {str(server.id) : server for server in all_entities('server')}
        ports = {str(port.id) : port for port in all_entities('port', details=True)}

        for a in addr:
            if a.port_id is None:
                print(f"{a.floating_ip_address:20}    -")
            else:
                srv_id = str(ports[str(a.port_id)].device_id)
                srv = servers[srv_id]
                print(f"{a.floating_ip_address:20}    {srv.name}")

    def info(self, file=None):
        """
        Print detailed information about the project's quota.

        Parameters
        ----------
        file:
            The file-like object to print the information to. Defaults to sys.stdout.
        """

        if file is None:
            file = sys.stdout

        qlist = self.quota()
        RORDER=['vm', 'cpu', 'ram', 'disk', 'floating_ip', 'network', 'diskspace']
        qlist.sort(key=lambda q: RORDER.index(q.rtype))

        print(f"Project: {self.project.name}", file=file)
        print(file=file)
        print("--------------------------------------------------------------------------", file=file)
        print("                                   user                  project          ", file=file)
        print("Resource          avail      usage      limit      usage      limit   unit", file=file)
        print("--------------------------------------------------------------------------", file=file)
        for q in qlist:
            print(f"{q.rtype:>12} " 
                  f"{q.uqty(q.available):>10} "
                  f"{q.uqty(q.usage):>10} "
                  f"{q.uqty(q.limit):>10} "
                  f"{q.uqty(q.project_usage):>10} "
                  f"{q.uqty(q.project_limit):>10} "
                  f"{'-' if q.unit is None else 'GiB':>6}"
                  , file=file)

