# my_netbird_collection/plugins/inventory/netbird_inventory.py
"""
NetBird dynamic *inventory* plugin for Ansible.

*   One Ansible host for every NetBird **peer**.
*   **All** peer attributes are exposed as host variables, so you can still
    group with `keyed_groups` in your YAML inventory source if you want.
*   TLS certificate verification is controlled by the standard
    ``validate_certs`` option (default **True**).
*   The ``host`` option **may include a custom port**—for example
    ``netbird.example.com:33073``—and the value is forwarded verbatim to the
    NetBird SDK.

Quick test after dropping this file in a plugin path and creating an
``inventory/netbird.yml`` source:

    ansible-inventory -i inventory/ --graph -vvvv
"""
from __future__ import annotations

from ansible.errors import AnsibleError
from ansible.module_utils._text import to_text
from ansible.plugins.inventory import BaseInventoryPlugin

DOCUMENTATION = r"""
name: netbird_inventory
plugin_type: inventory
short_description: Pull hosts (peers) from NetBird via the ``netbird`` Python SDK
version_added: "1.0.0"  # collection version
requirements:
  - netbird >= 1.1.0
options:
  plugin:
    description: Must be set to this plugin’s FQCN.
    required: true
    choices: ["my_netbird_collection.netbird_inventory"]
  host:
    description: >
      NetBird API hostname **without scheme**. You may append a custom port,
      e.g. ``api.netbird.io:33073`` for a self‑hosted instance.
    required: true
    type: str
  api_token:
    description: NetBird Personal Access Token.
    required: true
    type: str
    no_log: true
  validate_certs:
    description: Verify TLS certificates when connecting over HTTPS.
    type: bool
    default: true
  timeout:
    description: HTTP timeout in seconds.
    type: int
    default: 30
  base_path:
    description: Base path of the NetBird API if different from ``/api``.
    type: str
    default: /api
"""


class InventoryModule(BaseInventoryPlugin):
    """Dynamic inventory plugin for NetBird peers (no Constructable mix‑in)."""

    NAME = "my_netbird_collection.netbird_inventory"

    def verify_file(self, path):
        """Return *True* if this is a YAML file meant for this plugin."""
        return super().verify_file(path) and path.endswith(("netbird.yml", "netbird.yaml"))

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        self._read_config_data(path)

        # ------------------------------------------------------------------
        # 1. Collect plugin options
        # ------------------------------------------------------------------
        host = self.get_option("host")
        api_token = self.get_option("api_token")
        validate_certs = self.get_option("validate_certs")
        timeout = self.get_option("timeout")
        base_path = self.get_option("base_path")

        # ------------------------------------------------------------------
        # 2. Import NetBird SDK
        # ------------------------------------------------------------------
        try:
            from netbird import APIClient  # type: ignore
        except ImportError as exc:
            raise AnsibleError(
                "The 'netbird' Python package is required for this plugin "
                f"(pip install netbird): {to_text(exc)}"
            )

        # ------------------------------------------------------------------
        # 3. Initialise client (always HTTPS); validate_certs -> verify_ssl
        #    Note: ``host`` may include ":port"; SDK accepts it verbatim.
        # ------------------------------------------------------------------
        try:
            client = APIClient(
                host=host,
                api_token=api_token,
                use_ssl=True,
                verify_ssl=validate_certs,
                timeout=timeout,
                base_path=base_path,
            )
        except Exception as exc:
            raise AnsibleError(f"Failed to initialise NetBird client: {to_text(exc)}")

        # ------------------------------------------------------------------
        # 4. Retrieve peers and build inventory
        # ------------------------------------------------------------------
        try:
            peers = client.peers.list()  # List[Dict[str, Any]]
        except Exception as exc:
            raise AnsibleError(f"Failed to fetch peers: {to_text(exc)}")

        for peer in peers:
            # Determine inventory hostname: prefer dns_label → name → id
            hostname = peer.get("dns_label") or peer.get("name") or peer.get("id")
            if not hostname:
                continue  # skip peers without usable identifier

            self.inventory.add_host(hostname)

            # Map IP to Ansible default variable for convenience
            if peer.get("ip"):
                self.inventory.set_variable(hostname, "ansible_host", peer["ip"])

            # Expose every attribute as a host variable
            for key, value in peer.items():
                self.inventory.set_variable(hostname, key, value)
