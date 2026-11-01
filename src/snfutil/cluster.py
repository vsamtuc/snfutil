import io
import pathlib
import yaml
from subprocess import run, STDOUT

from .kamaki_run import all_entities, entity_info, resolve_entity
from .controller import ClusterController
from .specs import ClusterSpec, ServerSpec
from .server import Server


class Cluster(ClusterController):
    """
    This class offers a convenient api to control a cluster and
    make easy several operations. 

    Cluster(spec_source)

    where `spec_source` is one of:
    - A file-like object
    - A dict of options
    - A path name
    - A yaml-encoded spec
    """
    def __init__(self, spec_source):
        # Create from different sources
        # - try it as file-like
        # - then, try it as a file name
        # - then, try it as raw yaml
        self.yaml_file_path = None
        cluster_spec = None
        if isinstance(spec_source, io.IOBase):
            cluster_spec = ClusterSpec.from_file(spec_source)
        elif isinstance(spec_source, dict):
            cluster_spec = ClusterSpec(**spec_source)
        else:
            try:
                cluster_spec = ClusterSpec.from_yaml_file(spec_source)
                self.yaml_file = pathlib.Path(spec_source)
            except OSError:
                cluster_spec = ClusterSpec.from_yaml_text(spec_source)

        if cluster_spec is None:
            spec_repr = repr(spec_source)
            if len(spec_repr) > 50:
                spec_repr = spec_repr[:50] + "..."
            raise ValueError(f"Cannot read ClusterSpec from '{spec_repr}'")

        super().__init__(cluster_spec)
        

    def info(self, **kwargs):
        if self.yaml_file_path:
            print("Cluster:", self.yaml_file_path, **kwargs)
        print("Project:", self.cluster_spec.project.name, **kwargs)
        print("", **kwargs)

        goals = self.get_goals()
        sstates = self.get_states(goals.keys())
        print(f"  {'Server':16} {'ID':6} {'status':7} {'goal':7} {'storage':7} {'addresses':32}", 
                **kwargs)
        print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*32}", **kwargs)

        cl_volumes = {
            vol.id: vol for vol in all_entities('volume', details=True)
        }
        for srv in sorted(self.server_names):
            state = sstates[srv]
            srvid = state.id if hasattr(state, 'id') else '-'
            status = state.status if state.status else ''
            goal = str(goals[srv])
            if status == 'ACTIVE':
                # collect volume info
                vols = []
                stors = []
                for volid in state.volumes:
                    vol = cl_volumes.get(str(volid), None)
                    vols.append(vol)
                    if vol.image_id is None:
                        stors.append(f"{vol.size}")
                    else:
                        stors.append(f"({vol.size})")
                storage = ','.join(stors)

                # Collect addr info
                ipaddr = []
                for alist in state.addresses.values():
                    for a in alist:
                        if a['version'] == 4:
                            ipaddr.append(a['addr'])
                addresses = ', '.join(ipaddr)

            else:
                storage = '-'
                addresses = ''
            print(f"  {srv:16} {srvid:6} {status:7} {goal:7} {storage:7} {addresses:32}", **kwargs)

    def __repr__(self):
        return f"Cluster({self.cluster_spec.spec_ident()})"

    def __str__(self):
        return repr(self)

    def get_servers(self):
        return [Server(state) 
                for state in self.get_states().values()]

    def save_ssh_config(self, ssh_conf_path, mode='x', partial=False):
        """Save SSH configuration files.

        Generate an 'ssh_config' file and a 'known_hosts' file fragment,
        for the current cluster state. These files can be added to
        the user's SSH configuration to enable seamless access to the
        cluster servers.
        
        Parameters
        ----------
        ssh_conf_path: path-like
            The path to the ssh-config file to be created.
        mode (='x'): str
            The mode used to create the new files. The default is 'x',
            ensuring that existing files will not be overwritted unwittingly.
        partial (=False): bool
            If False (default), the method will fail if there are servers
            who are not ACTIVE.
        """
        import pathlib
        ssh_conf_path = pathlib.Path(ssh_conf_path)
        ssh_known_path = ssh_conf_path.with_suffix('.known_hosts')

        # Check if some servers are not ACTIVE
        servers = self.get_servers()
        active_servers = [srv for srv in servers if srv.status == 'ACTIVE']

        if len(active_servers) < len(servers) and not partial:
            raise RuntimeError(f"There are {len(servers)-len(active_servers)}"
                               f" servers that are not ACTIVE.")
        if len(active_servers) == 0:
            return
        # 
        with open(ssh_known_path, mode=mode) as kh:
            self._print_ssh_known_hosts(kh, active_servers)

        with open(ssh_conf_path, mode=mode) as f:
            self._print_ssh_config(f, active_servers, ssh_known_path)

    def _print_ssh_known_hosts(self, file, servers):
        """Print the host keys of servers to file."""

        # Create the input to ssh-keyscan. It is a list of
        # (addr ,  namelist) lines.
        with io.StringIO() as addr_name_file:
            for srv in servers:
                pub_nets = [n.id
                            for n in srv.attached_networks()
                            if n.public]
                fip, = [a.addr for a in srv.flatten_addresses()
                        if a.version == 4 and a.type == 'floating']
                hn = srv.hostname()
                fqdn = srv.fqdn()
                # Get public IPs
                fips = [a.addr for a in srv.flatten_addresses()
                        if a.netid in pub_nets]
                sshnames = [fqdn, hn, *fips]
                namelist = ','.join(sshnames)
                print(f"{fip} {namelist}", file=addr_name_file)
            addr_names = addr_name_file.getvalue()

        cproc = run(['ssh-keyscan', '-f', '-', ],
                    text=True,
                    stdout=file,
                    stderr=STDOUT,
                    input=addr_names,
                    check=True)
        cproc.check_returncode()

    def _print_ssh_config(self, file, servers, known_hosts=None):
        for srv in servers:
            dns_name = srv.fqdn()
            duser = srv.metadata['users']
            print(f"Host {srv.name}", file=file)
            print(f"    Hostname {dns_name}", file=file)
            print(f"    User {duser}", file=file)
            if known_hosts is not None:
                print(f"    UserKnownHostsFile={known_hosts}", file=file)
            print(file=file)


    def inventory(self, *args):
        # Check the type of output needed
        if len(args) == 2 and args[1] == '--list':
            return self.inventory_list()
        if len(args) == 3 and args[1] == '--host':
            host = args[2]
            return self.inventory_host(host)
        raise ValueError(f"Improper arguments, expected either 2 or 3")

    def inventory_host(self, host):
        raise NotImplementedError(f"Cannot display inventory for {host}")
    
    def expand_value(self, val, loc_vars):
        if val:
            if isinstance(val, str) and val.startswith('(') and val.endswith(')'):
                return eval(val[1:-1], globals(), loc_vars)
            if isinstance(val, list):
                return [self.expand_value(v, loc_vars) for v in val]
            if isinstance(val, dict):
                return {
                    k: self.expand_value(v, loc_vars) 
                    for k, v in val.items()
                }
            # Fall through...
        return val

    def inventory_list(self):
        servers = self.get_servers()
        specs = self.server_spec
        invry = dict()


        if self.spec.hostvars is not None:
            # Process host vars
            hostvars = dict()
            for server in servers:
                spec = specs[server.name]
                loc_vars = {
                    'cluster': self,
                    'host': server,
                    'spec': spec,
                }
                vars = dict()

                # Generate host vars
                hostvars[server.name] = {
                    var: self.expand_value(val, loc_vars)
                    for var, val in self.spec.hostvars.items()
                }
            invry['_meta'] = {
                'hostvars': hostvars
            }

        if self.spec.inventory is not None:
            clu_vars = {
                'cluster': self
            }
            invry.update(self.expand_value(self.spec.inventory, clu_vars))

        import sys, json
        json.dump(invry, sys.stdout, indent=2)
        return 0
    