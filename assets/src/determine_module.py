import importlib.util
from typing import List, Any

import sys

from assets.src import schemas


async def get_module_name(d, configuration) -> Any | None:
    names = [a for a in (d.cluster_name, d.former_cluster_name, d.last_known_cluster_name) if a]
    if names:
        return names[0]
    else:
        return None


async def notify(data: List[schemas.Node], configuration) -> List[schemas.Node]:
    if data:
        for idx, d in enumerate(data):
            latest_known_cluster = await get_module_name(
                d, configuration
            )
            if latest_known_cluster:
                module = set_module(latest_known_cluster, configuration)
                data[idx] = module.mark_notify(d, configuration)
    return data


def set_module(cluster_name, configuration):
    if cluster_name:
        spec = importlib.util.spec_from_file_location(
            f"{cluster_name}.build_embed",
            f"{configuration['file settings']['locations']['cluster modules']}/{cluster_name}.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{cluster_name}.build_embed"] = module
        spec.loader.exec_module(module)
        return module
