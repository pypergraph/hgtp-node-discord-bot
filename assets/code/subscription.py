import asyncio
import logging
import re
import shutil
import sys
from datetime import datetime

from aiofiles import os
import pandas as pd


import dask.dataframe as dd

from assets.code import node, api
from assets.code.discord.services import bot

IP_REGEX = "^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$"


async def check(dask_client, latest_tessellation_version, requester, subscriber_dataframe, history_dataframe, all_cluster_data, dt_start, process_msg, _configuration):
    futures = []
    data = []
    for id_ in await locate_ids(dask_client, requester, subscriber_dataframe):
        subscriber = await locate_node(dask_client, subscriber_dataframe, id_)
        for L in list(set(subscriber["layer"])):
            print(L)
            for port in subscriber.public_port[subscriber.layer == L]:
                futures.append(asyncio.create_task(
                    node.check(dask_client, bot, process_msg, requester, subscriber, port, L,
                               latest_tessellation_version, history_dataframe, all_cluster_data, dt_start,
                               _configuration)))
    for async_process in futures:
        try:
            d, process_msg = await async_process
            data.append(d)
        except Exception as e:
            logging.critical(repr(e.with_traceback(sys.exc_info())))
            exit(1)
    return data


async def update_public_port(dask_client, node_data):
    pass


async def locate_ids(dask_client, requester, subscriber_dataframe):
    if requester is None:
        return list(set(await dask_client.compute(subscriber_dataframe["id"])))
    else:
        return list(set(await dask_client.compute(
            subscriber_dataframe["id"][subscriber_dataframe["contact"].astype(dtype=int) == int(requester)])))


async def locate_node(dask_client, subscriber_dataframe, id_):
    return await dask_client.compute(subscriber_dataframe[subscriber_dataframe.id == id_])


async def write(dask_client, dataframe, configuration):
    dataframe = dataframe.repartition(npartitions=1)

    fut = dataframe.to_parquet(f'{configuration["file settings"]["locations"]["subscribers temp"]}',
                               overwrite=True, compute=False, write_index=False)
    await dask_client.compute(fut)
    if await os.path.exists(f'{configuration["file settings"]["locations"]["subscribers_new"]}'):
        shutil.rmtree(f'{configuration["file settings"]["locations"]["subscribers_new"]}')
    await os.rename(f'{configuration["file settings"]["locations"]["subscribers temp"]}', f'{configuration["file settings"]["locations"]["subscribers_new"]}')
    # Write the updated DataFrame to the temporary location


async def read(configuration: dict):
    logging.info(f"{datetime.utcnow().strftime('%H:%M:%S')} - READING SUBSCRIBER DATA AND RETURNING DATAFRAME")
    if not await os.path.exists(configuration["file settings"]["locations"]["subscribers_new"]):
        print("SUB NOT EXISTS")
        return dd.from_pandas(pd.DataFrame(columns=configuration["file settings"]["columns"]["subscribers_new"]), npartitions=1)
    elif await os.path.exists(configuration["file settings"]["locations"]["subscribers_new"]):
        return dd.read_parquet(configuration["file settings"]["locations"]["subscribers_new"])


def slice_args_per_ip(args):
    sliced_args = []
    ips = list(set(filter(lambda ip: re.match(IP_REGEX, ip), args)))
    ip_idx = list(set(map(lambda ip: args.index(ip), ips)))
    for i in range(0, len(ip_idx)):
        if i + 1 < len(ip_idx):
            arg = args[ip_idx[i]: ip_idx[i + 1]]
            sliced_args.append(arg)
        else:
            arg = args[ip_idx[i]:]
            sliced_args.append(arg)
    return sliced_args


def clean_args(arg) -> tuple[list[int | None], list[int | None], str | None]:
    ip = None
    public_zero_ports = []
    public_one_ports = []

    for i, val in enumerate(arg):
        if re.match(IP_REGEX, val):
            ip = val
        elif val in ("z", "zero"):
            for port in arg[i + 1:]:
                if port.isdigit():
                    public_zero_ports.append(int(port))
                else:
                    break
        elif val in ("o", "one"):
            for port in arg[i + 1:]:
                if port.isdigit():
                    public_one_ports.append(int(port))
                else:
                    break
    return public_zero_ports, public_one_ports, ip


async def validate_subscriber(ip: str, port: str, configuration):
    """Will need refactoring before metagraph release. Some other way to validate node?"""
    print("Requesting:", f"http://{str(ip)}:{str(port)}/node/info")
    node_data = await api.safe_request(f"http://{ip}:{port}/node/info", configuration)
    return node_data["id"] if node_data is not None else None
