"""Read the hand-written YAML files, refusing a key that appears twice in one mapping.

Plain ``yaml.safe_load`` keeps the last of two ``year:`` lines in an entry without a word, so
a copy-and-paste slip can silently change a date. ``load_yaml`` raises ``yaml.YAMLError``
instead, which the loaders already report as a normal problem with the file.
"""

from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

_MERGE_TAG = "tag:yaml.org,2002:merge"


class UniqueKeyLoader(yaml.SafeLoader):
    """A ``SafeLoader`` that raises ``ConstructorError`` on a repeated mapping key."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            if key_node.tag == _MERGE_TAG:  # "<<: *anchor" may repeat; it is not a real key
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                repeated = key in seen
            except TypeError:  # an unhashable key; the parent class reports it
                continue
            if repeated:
                raise ConstructorError(
                    "while reading a mapping",
                    node.start_mark,
                    f"found the key {key!r} twice",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(text: str) -> Any:
    """The data in ``text``, like ``yaml.safe_load``, but a repeated key is an error."""
    return yaml.load(text, Loader=UniqueKeyLoader)
