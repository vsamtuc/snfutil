import io
import logging
from subprocess import run, STDOUT
import json
import yaml
from .core import options_to_args, SnfObject, ENTITIES

# When non-null, specify a non-default cloud
CLOUD=None

def _run_kamaki(cmd: list[str]):
    global VERBOSE, CLOUD
    logger = logging.getLogger("kamaki")
    if CLOUD:
        cmd = list(cmd).extend(['--cloud', CLOUD])

    # printable command
    pcmd = ' '.join(cmd)
    logger.info("Executing: %s", pcmd)
    cout = run(cmd, capture_output=True)
    logger.debug("Execution return code: %d", cout.returncode)
    if cout.returncode:
        raise RuntimeError(str(cout))
    return cout

def config_clouds():
    bopts = _run_kamaki(['kamaki', 'config', 'list']).stdout
    with io.BytesIO(bopts) as f:
        blines = f.readlines()
    btokens = [l.split(b' ') for l in blines]
    # first collect all cloud names
    clouds = set()
    default_cloud = None
    for btok in btokens:
        if btok[0].startswith(b'cloud.'):
            bcloud = btok[0].split(b'.')[1]
            clouds.add(bcloud.decode('ascii'))
        elif btok[0] == b'global.default_cloud':
            default_cloud = btok[1].decode('ascii').strip()
    
    if default_cloud not in clouds:
        raise RuntimeError(f"Malformed options: default cloud '{default_cloud}' not in {clouds}")
    return clouds, default_cloud

def default_cloud():
    return config_clouds()[1]

def all_clouds():
    return config_clouds()[0]

def current_cloud():
    global CLOUD
    if CLOUD is not None:
        return CLOUD
    else:
        return default_cloud()

def kamaki(*args, **kwargs):
    """Used to execute kamaki commands and return the result as json.
    """
    cargs = [str(a) for a in args]
    options = {'output_format': 'json'}
    options.update(kwargs)
    cmd = ['kamaki', *cargs, *options_to_args(options)]
    cout = _run_kamaki(cmd)
    if options.get('output_format', False) is False:
        return
    try:
        try:
            return json.loads(cout.stdout)
        except json.JSONDecodeError:
            try:
                with io.StringIO(cout.stdout) as f:
                    return yaml.safe_load(f)
            except yaml.YAMLError:
                return cout.stdout
    except Exception as e:
        raise RuntimeError(str(cout)) from e

def kamaki_cmd(*args, **kwargs):
    """Execute the kamaki command for commands that do not return output"""
    cargs = [str(a) for a in args]
    options = {}
    options.update(kwargs)
    cmd = ['kamaki', *cargs, *options_to_args(options)]
    cout = _run_kamaki(cmd)
    if len(cout.stderr):
        raise RuntimeError(cout.stderr)
    if cout.stdout.startswith(b"Syntax error\n"):
        raise RuntimeError(cout.stdout)

def all_entities(entcls, where=None, select=None, **options):
    if entcls not in ENTITIES:
        raise NameError(f"Entity {entcls} is unknown")
    optargs = options_to_args(options)
    ent = kamaki(entcls, 'list', *optargs)
    ent = map(SnfObject, ent)
    if where is not None:
        ent = filter(where, ent)
    if select is not None:
        ent = (e % select for e in ent)
    return list(ent)


def entity_info(entcls, ent_id, **options):
    ent = kamaki(entcls, 'info', str(ent_id), **options)
    return SnfObject(ent)


def show_all(entcls, where=None, select=None, **options):
    for e in all_entities(entcls, where=where, select=select, **options):
        print(e)


def fetch_entity(entcls, where, optional=False, info=False, **options):
    """
    Return the unique entity matching selector.

    Attributes
    ----------
    entcls:
        The entity class
    where:
        A callable by which to filter all entities
    optional (=False): bool
        If true, return `None` if no match is found.
    info (=False): bool
        If true, return entity info object.
    """
    fl = list(all_entities(entcls, where=where, **options))
    if optional and not fl:
        return None
    if len(fl) != 1:
        logger = logging.getLogger("kamaki")
        logger.debug("NonUnique entity match in fetch_entity for %s: %d matches", entcls, len(fl))
        for e in fl:
            logger.debug("  Match %s", e)
        raise ValueError("fetch_entity: "
                         f"{len(fl)} entities '{entcls}' match filter")
    ent = fl[0]
    if info:
        ent = entity_info(entcls, ent.id)
    return ent


def resolve_entity(entcls, sel, optional=False, info=False, **options):
    """Select an entity by a flexible spec    
    """
    if isinstance(sel, SnfObject):
        # turn into dict
        sel = SnfObject.asdict(sel)

    if isinstance(sel, dict):
        def matcher(e):
            return all( hasattr(e, attr) and str(sel[attr]) == str(getattr(e, attr))
                        for attr in sel )
    elif callable(sel):
        matcher = sel
    elif sel is None:
        return None
    else:
        def matcher(e):
            return any(getattr(e, attr, None) == sel
                       for attr in ('name', 'id'))
    return fetch_entity(entcls, matcher, optional=optional, info=info, **options)

