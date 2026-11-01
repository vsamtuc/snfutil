import logging
import pytest
from snfutil import *

pytestmark = pytest.mark.expensive

def test_load_yaml(caplog):
    caplog.set_level(logging.INFO)
    from textwrap import dedent
    spec_yaml = dedent("""\
        num_nodes: 10
        project: stelar-project.eu
        flavor: C16R16384D30ext_urbd_cached
        image: Debian Cloud
        key: stelar01
        networks:
        - skn_private
        - id: 3510
          ipaddr:
          - 83.212.80.247
          - 83.212.80.248
          - 83.212.80.249
          - 83.212.80.250
          - 83.212.80.252
          - 83.212.80.253
          - 83.212.80.254
          - 83.212.80.255
          - 83.212.81.0
          - 83.212.81.1
        name_pattern: skube%02d
        """)
    #breakpoint()
    cspec = ClusterSpec.from_yaml_text(spec_yaml)

    assert cspec.num_nodes == 10

YSPEC = """\
num_nodes: 2
project: dsys2021.softnet.tuc.gr
flavor: C4R4096D30ext_urbd_cached
image: Debian Cloud
key: stelar02
networks:
- '3510'
name_pattern: foonode%02d
"""

def test_read_yaml(caplog):
    caplog.set_level(logging.INFO, logger="kamaki")
    cs = ClusterSpec.from_yaml_text(YSPEC)
    assert cs.num_nodes == 2
    assert cs.project.name == 'dsys2021.softnet.tuc.gr'
    assert cs.key.name == 'stelar02'

    specs = cs.make()

    assert len(specs) == cs.num_nodes
    # Note: spec.key is a name, not an object !!
    assert all(spec.key == 'stelar02' for spec in specs)

    assert all(len(spec.networks) == 1 for spec in specs)
    assert all(spec.networks[0][0] == '3510' for spec in specs)
    assert all(spec.networks[0][1].startswith('83') for spec in specs)

