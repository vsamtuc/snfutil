from .core import SnfObject
from .kamaki_run import all_entities, entity_info

class Server(SnfObject):
    """
    Accepts a server object (dict or SnfObject) and implements 
    added-value functions.
    """
    
    def __init__(self, server_obj):
        if not isinstance(server_obj, (dict, SnfObject)):
            raise TypeError(f"Expected a dict or SnfObject, got {type(server_obj)} {server_obj}")
        if isinstance(server_obj, SnfObject):
            server_obj = server_obj.__getstate__()
        super().__init__(server_obj)

    def flatten_addresses(self):
        """Return a list of pairs (address, network_id) for every IP address
        """
        for netid in self.addresses:
            for addr in self.addresses[netid]:
                yield SnfObject({
                    'netid': netid,
                    'type': addr['OS-EXT-IPS:type'],
                    'version': addr['version'],
                    'addr': addr['addr']
                })

    def fqdn(self):
        """Return the FQDN (Fully Qualified Domain Name) of the server"""
        return self['SNF:fqdn']
    
    def hostname(self):
        """Return the hostname, as the first component of the FQDN"""
        return self.fqdn().split('.')[0]
    
    def attached_networks(self):
        """Return the networks that the server is attached to"""
        for netid in self.addresses:
            yield entity_info('network', netid)

    def attached_volumes(self):
        """Return the attached volumes"""
        myvols = set(map(str, self.volumes))
        return [vol
                for vol in all_entities('volume', details=True)
                if vol.tenant_id == self.tenant_id and vol.id in myvols]

