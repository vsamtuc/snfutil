from __future__ import annotations
import logging
import time
from typing import Union, TYPE_CHECKING

from .core import SnfObject, options_to_args
from .kamaki_run import all_entities, entity_info, kamaki_cmd, kamaki
from .planner import Planner

if TYPE_CHECKING:
    from snfutil.specs import ServerSpec


class ClusterController:
    """
    This class implements a controller for a cluster.

    The controller is responsible for managing the resources
    of a cluster according to a spec.
    """
    def __init__(self, cluster_spec):
        self.cluster_spec = cluster_spec

        # store server specs
        sspecs = cluster_spec.make()
        self._server_specs = sspecs
        self._server_names = [spec.name for spec in sspecs]
        self._server_spec = {
            spec.name: spec for spec in sspecs
        }

        self.logger = logging.getLogger("controller")

    @property
    def spec(self):
        return self.cluster_spec

    @property
    def server_specs(self):
        return self._server_specs

    @property
    def server_names(self):
        return self._server_names

    @property
    def server_spec(self):
        return self._server_spec

    def activate(self):
        # Set goal for all servers
        for server in self.server_specs:
            server.set_status('ACTIVE')
        self.apply_spec()

    def deactivate(self):
        # Set goal for all servers
        for server in self.server_specs:
            server.set_status(None)
        self.apply_spec()

    def get_goals(self):
        return {spec.name: spec.status for spec in self.server_specs}

    def apply_spec(self):
        # Apply the server spec
        self.apply_server_spec()

        # If we have a goal to be active, apply volume spec
        if all(spec.status == 'ACTIVE' for spec in self.server_specs):
            self.apply_volume_spec()

    def apply_server_spec(self):

        ###########################
        # The consolidation loop
        ########################### 
        while True:
            goals = self.get_goals()

            # Get current status
            states = self.get_states(goals.keys())
            for srv in states.values():
                if 'progress' in srv:
                    self.logger.info("%s: progress %d", srv.name, srv.progress)
                if 'diagnostics' in srv:
                    for d in srv.diagnostics:
                        self.logger.info("%s: %s", srv.name, d['message'])

            # Do one transition for each server
            actions = 0
            for server in states:
                actions += self.transition_server(server, 
                                                  states[server], 
                                                  goals[server])
            if not actions:
                break

            # Give the cloud server a rest :-)
            time.sleep(0.5)

    def transition_server(self, server, state, goal):
        # Get the current status
        assert goal != 'ERROR'
        status = state.status
        try:
            task_state = state['SNF:task_state']
        except KeyError:
            task_state = None

        self.logger.info(f"{server}  {status}  {task_state}   {goal}")

        if task_state:
            return 1

        if status == goal:
            return 0
        
        if status == 'BUILD':
            return 1
        
        if status is None:
            if goal == 'ACTIVE':
                return self.transition_server(server, state, 'BUILD')
            if goal == 'BUILD':
                return self.create_server(server)
            if goal == 'DELETED':
                # This cannot be done, but it is possible that it is detected!
                try:
                    return self.forget_server(server)
                except KeyError:
                    return 1

        if status == 'ACTIVE':
            if goal is None:
                return self.transition_server(server, state, 'DELETED')
            if goal == 'DELETED':
                return self.delete_server(state)
            
        if status == 'ERROR':
            assert goal in ('BUILD', 'ACTIVE', 'DELETED', None)
            if goal == 'DELETED':
                return self.delete_server(state)
            else:
                return self.transition_server(server, state, 'DELETED')

        if status == 'DELETED':
            if goal is None:
                return self.forget_server(state)
            return self.transition_server(server, state, None)

        assert False

    def create_server(self, server, **options):

        options |= {'wait':True}

        spec = self.server_spec[server]
        self.logger.info("Creating server %s", server)

        cmd = spec.command()
        cmd.extend(options_to_args(options))
        state = kamaki(*cmd)
        build_state = SnfObject(state)

        # We need to save the server build_state !
        self.logger.fatal("Creating %s with id %s and root password '%s'", 
                    build_state.name,
                    build_state.id,
                    build_state.adminPass)

        return 1

    def delete_server(self, state):
        self.logger.warn("Server %s is being deleted", state.name)
        kamaki_cmd('server', 'delete', state.id)
        return 1

    def forget_server(self, state):
        # Nothing here for now
        self.logger.warn("Server %s is now forgotten", state.name)
        return 1

    def create_volume(self, server, name, size):
        kamaki('volume', 'create',
            '--server-id', server.id,
            '--project-id', server.tenant_id,
            '--name', name,
            '--size', size,
            output_format=False, # This is needed, because
            # kamaki returns junk that raises an exception! 
            # Note: It is not clear what will happen if there is
            # an actual error !!
            wait=True
            # Apparently, we cannot spawn volume creation routines
            # in parallel !
            )
        self.logger.info(f"Created volume '{name}' ({size} GiB) on {server.name}")

    def apply_volume_spec(self, dry_run=False):
        """Create volumes for servers. 
        
        This is called only when the cluster goal is 'ACTIVE'
        """
        assert all(s.status == 'ACTIVE' for s in self.server_specs)
        states = self.get_states()

        # Ensure that we are at a total ACTIVE state
        # If not, we should not proceed to volume creation
        if not all(state.status == 'ACTIVE' for state in states.values()):
            self.logger.error("Cannot apply volume spec, "
                                "since some servers are not ACTIVE")
            return

        # Check each server spec
        class VolumeBuilder:
            def __init__(self, server, name, size):
                self.server = server
                self.name = name
                self.size = size
            def __str__(self):
                return f"Volume {self.name} {self.size}GiB on  {self.server.name}"

        deferred_volumes = []
        for srv_name, state in states.items():
            spec = self.server_spec[srv_name]

            # Check that the server is partially conformant
            # Skip first volume, as it contains image [ARE WE SURE ABOUT THIS?]
            # Note: state.volumes contains integers, so we fix it...
            state_volumes = [str(volid) for volid in state.volumes[1:]]
            errors = 0

            # Check compatibility 
            for vol_id, vol_spec in zip(state_volumes, spec.volumes):
                vol = entity_info('volume', vol_id)
                if (vol.display_name, vol.size) != vol_spec:
                    errors += 1

            if errors > 0 or len(state_volumes) > len(spec.volumes):
                self.logger.error("Server volumes incompatible with spec")
                continue  # to next server

            # Ok, we can create the rest of spec.volumes
            for vol_spec in spec.volumes[len(state_volumes):]:
                b = VolumeBuilder(state, vol_spec[0], vol_spec[1])
                deferred_volumes.append(b)
        
        # Check that we can create all the volumes.
        avail = Planner(spec.project).quota('disk').avail_GiB
        needed = sum(v.size for v in deferred_volumes)

        if needed > avail:
            raise RuntimeError(f"Insufficient space, need {needed} "
                               f"GiB but only {avail} GiB available.")

        if dry_run:
            print("Creating volumes:")
            for vb in deferred_volumes:
                print(vb)
            return

        # Ok, we can create the volumes
        for vb in deferred_volumes:
            self.create_volume(vb.server, vb.name, vb.size)

    def get_states(self, servers=None):
        """Return the current state for each server in `servers`.

        At a minimum, the 'name' and 'status' fields will appear.
        For servers that are not instantiated, 'status' will be None.
        """
        if servers is None:
            servers = self.server_names

        def matcher(s):
            return s.name in servers and s.tenant_id == self.cluster_spec.project.id
        
        sstates = all_entities('server',
                               where=matcher,
                               details=True)
        
        states = {s.name: s for s in sstates}
        for server in servers:
            if server not in states:
                ss = {'name': server, 'status': None}
                sstate = SnfObject(ss)
                states[server] = sstate

        return states
