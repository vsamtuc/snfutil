import io
import logging
from subprocess import run
import json
import yaml
from .core import options_to_args, SnfObject, ENTITIES

# When non-null, specify a non-default cloud
CLOUD = None


def _run_kamaki(cmd: list[str]):
    """
    Execute a kamaki command and return the result.

    This is a low-level function that is used internally to 
    execute kamaki commands.

    Parameters
    ----------
    cmd: list[str]
        The command to execute as a list of strings.

    Returns
    -------
    CompletedProcess
        The result of the executed command.
    """

    # global CLOUD
    logger = logging.getLogger("kamaki")
    if CLOUD:
        cmd = list(cmd) + ['--cloud', CLOUD]

    # printable command
    pcmd = ' '.join(cmd)
    logger.info("Executing: %s", pcmd)
    cout = run(cmd, capture_output=True)
    logger.debug("Execution return code: %d", cout.returncode)
    if cout.returncode:
        raise RuntimeError(str(cout))
    return cout


def config_clouds():
    """
    Return the available cloud configurations and the 
    default cloud.

    Returns
    -------
    tuple[set[str], str]
        A tuple containing the set of all cloud names and the default cloud name.
    """
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
    """
    Return the default cloud name.

    Returns
    -------
    str
        The default cloud name.
    """
    return config_clouds()[1]


def all_clouds():
    """
    Return the set of all available cloud names.

    Returns
    -------
    set[str]
        The set of all cloud names.
    """
    return config_clouds()[0]


def current_cloud():
    """
    Return the currently selected cloud name.

    Returns
    -------
    str
        The current cloud name.
    """
    # global CLOUD
    if CLOUD is not None:
        return CLOUD
    else:
        return default_cloud()


def kamaki(*args, **kwargs):
    """
    Execute kamaki commands and return the result as json.

    Parameters
    ----------
    *args:
        Positional arguments for the kamaki command.
    **kwargs:
        Keyword arguments for the kamaki command.

    Returns
    -------
    dict or list or str or None
        The parsed JSON or YAML output, or raw stdout if parsing fails, or None if output_format is False.
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
    """
    Execute the kamaki command for commands that do not return output
    Parameters
    ----------
    *args:
        Positional arguments for the kamaki command.
    **kwargs:
        Keyword arguments for the kamaki command.

    Returns
    -------
    None
        Raises RuntimeError if the command fails or returns an error.
    """
    cargs = [str(a) for a in args]
    options = {}
    options.update(kwargs)
    cmd = ['kamaki', *cargs, *options_to_args(options)]
    cout = _run_kamaki(cmd)
    if len(cout.stderr):
        raise RuntimeError(cout.stderr)
    if cout.stdout.startswith(b"Syntax error\n"):
        raise RuntimeError(cout.stdout)


def all_entities(entcls, where=None, select=None, **options) -> list[SnfObject]:
    """
    Retrieve all entities of a given class, optionally filtered and selected.

    Parameters
    ----------
    entcls:
        The entity class.
    where:
        A callable to filter entities.
    select:
        A list of attributes to select from each entity.
    **options:
        Additional options for the kamaki command.

    Returns
    -------
    list
        A list of entities matching the criteria.
    """
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


def entity_info(entcls: str, ent_id: str, **options) -> SnfObject | None:
    """
    Retrieve information about a specific entity.

    Parameters
    ----------
    entcls:
        The entity class.
    ent_id:
        The ID of the entity.
    **options:
        Additional options for the kamaki command.

    Returns
    -------
    SnfObject
        The entity information wrapped in a SnfObject.
    
        Raises RuntimeError if the entity does not exist.
    """
    ent = kamaki(entcls, 'info', str(ent_id), **options)
    return SnfObject(ent)


def show_all(entcls, where=None, select=None, **options):
    """
    Show all entities of a given class, optionally filtered and selected.

    Parameters
    ----------
    entcls:
        The entity class.
    where:
        A callable to filter entities.
    select:
        A list of attributes to select from each entity.
    **options:
        Additional options for the kamaki command.
    """
    for e in all_entities(entcls, where=where, select=select, **options):
        print(e)


def fetch_entity(entcls, where, optional=False, info=False, **options):
    """
    Return the unique entity matching selector.

    Parameters
    ----------
    entcls:
        The entity class
    where:
        A callable by which to filter all entities
    optional (=False): bool
        If true, return `None` if no match is found.
    info (=False): bool
        If true, return entity info object instead of the entity itself.
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


def resolve_entity(entcls, sel, 
                   optional=False, info=False, **options
                   ) -> SnfObject | None:
    """
    Select an entity by a flexible spec.

    Parameters
    ----------
    entcls:
        The entity class.
    sel:
        The selection criteria, which can be a SnfObject, 
        dict, callable, string, or None.
    optional (=False): bool
        If true, return `None` if no match is found.
    info (=False): bool
        If true, return entity info object instead of the
        entity itself.
    **options:
        Additional options for the kamaki command.
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

