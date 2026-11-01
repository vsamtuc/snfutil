from __future__ import annotations
import io
import pprint

ENTITIES = [
    'project', 'server', 'ip', 'flavor', 'image',
    'keypair', 'user',
    'volume', 'network', 'port', 'subnet'
]

STATUS = [
    'BUILD',
    'ACTIVE',
    'STOPPED',
    'REBOOT',
    'ERROR'
]


def options_to_args(options):
    args = []
    for opt, val in options.items():
        # change underscores to dashes
        option = '--' + opt.replace('_', '-')
        if val is False:
            continue
        elif val in (None, True, ...):
            args.append(option)
        elif isinstance(val, (tuple, list)):
            for v in val:
                args.extend([option, str(v)])
        else:
            args.extend([option, str(val)])
    return args


class SnfObject:
    """Represents various Synnefo objects, represented as JSON internally.

    SnfObject(obj: dict|SnfObject)
    """
    def __init__(self, obj: dict|SnfObject):
        if isinstance(obj, SnfObject):
            self.__obj = SnfObject.asdict(obj)
        elif isinstance(obj, dict):
            self.__obj = obj
        else:
            raise TypeError(f"Expected dict, got {obj}")

    def __getattr__(self, attr):
        try:
            return self.__obj[attr]
        except KeyError:
            raise AttributeError(attr)

    def __getitem__(self, item):
        return self.__obj[item]

    def __contains__(self, item):
        return item in self.__obj

    def __truediv__(self, attr):
        obj = {a: self.__obj[a] for a in self.__obj if a not in attr}
        return SnfObject(obj)

    def __mod__(self, attr):
        obj = {a: self.__obj[a] for a in attr if a in self.__obj}
        return SnfObject(obj)

    def __pos__(self):
        return self.__obj

    def __iter__(self):
        return iter(self.__obj)
    
    def __len__(self):
        return len(self.__obj)

    def __repr__(self):
        return repr(self.__obj)

    def __getstate__(self):
        return self.__obj

    def __setstate__(self, state):
        self.__obj = state

    def __str__(self):
        with io.StringIO() as f:
            pprint.pprint(self.__obj, sort_dicts=False, stream=f, compact=True)
            return f.getvalue()

    @staticmethod
    def asdict(snf: SnfObject) -> dict:
        return snf.__obj
    
    @classmethod
    def make(cls, **attr):
        return cls(attr)