# Example plugin: copy elsewhere, add to config under plugin_modules, and adjust.
#
#   plugin_modules:
#     - /home/you/.config/open-loupedeck/plugins/custom_action.py
#
# Then bind with:
#   - match: { type: button, id: "3", edge: down }
#     actions:
#       - type: demo.log
#         message: "hello"

import logging

from open_loupedeck.actions.registry import register_action

logger = logging.getLogger("demo.plugin")


@register_action("demo.log")
class DemoLog:
    async def run(self, ctx, params):
        logger.info("demo.log: %s", params.get("message", ""))
