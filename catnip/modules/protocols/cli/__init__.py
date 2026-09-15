"""Click command groups for the protocol tools.

Kept in this import-cheap subpackage instead of inside each protocol
package: ``modules/protocols/<x>/__init__.py`` eagerly pulls in matplotlib,
the ``meshtastic`` library and ``fcntl``, so importing a ``cli`` module from
there would drag all of it into every ``catnip --help``.
"""
