"""Include fixed narration resources from the checkout or self-contained sdist."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class NarrationResources(BuildHookInterface):
    """Use archive-local resources when rebuilding the companion source archive."""

    def initialize(self, version: str, build_data: dict) -> None:
        """Select the three required resources without copying or installing them."""
        root = Path(self.root)
        resources = {
            "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
            "integrations/qwen/tts.json": "narration/integrations/qwen/tts.json",
            "docs/integrations/measured-narration.md": "narration/docs/integrations/measured-narration.md",
        }
        for source, destination in resources.items():
            selected = root / destination
            if not selected.is_file():
                selected = root.parent.parent / source
            if not selected.is_file():
                raise FileNotFoundError(f"Required narration resource is absent: {source}")
            build_data["force_include"][str(selected)] = destination
