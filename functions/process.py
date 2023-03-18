import logging
from datetime import datetime
import asyncio
from functions import read, request, latest_cluster_data, historic_cluster_data


async def get_clusters(cluster_layer, cluster_names, configuration):
    cluster_data = []
    for cluster_name, cluster_info in cluster_names.items():
        for lb_url in cluster_info["url"]:
            response = list(await request.Request(f"{lb_url}/{configuration['request']['url']['endings']['cluster']}").json(configuration))
            if response is not None:
                state = "online"
            else:
                state = "offline"
            data = {
                "layer": cluster_layer,
                "cluster name": cluster_name,
                "data": response,
                "state": state
            }
            print(data["cluster name"], data["state"])
        cluster_data.append(data)
        del lb_url
    return cluster_data


async def get_preliminaries(configuration):
    tasks = []
    cluster_data = []
    validator_data = await request.validator_data(configuration)
    latest_tessellation_version = await request.latest_project_version_github(f"{configuration['request']['url']['github']['api url']}{configuration['request']['url']['github']['tessellation']['latest release']}", configuration)
    for cluster_layer, cluster_names in list(configuration["request"]["url"]["load balancer"].items()):
        tasks.append(asyncio.create_task(get_clusters(cluster_layer, cluster_names, configuration)))
    for task in tasks:
        cluster_data.extend(await task)
    return cluster_data, validator_data, latest_tessellation_version


async def do_checks(dask_client, subscriber, layer, port, latest_tessellation_version, all_supported_clusters_data, history_dataframe, configuration):
    try:
        node_data, cluster_data = await request.node_cluster_data(subscriber, port, configuration)
        node_data = await latest_cluster_data.merge(layer, latest_tessellation_version, node_data, cluster_data, configuration)
        historic_node_dataframe = await historic_cluster_data.get_node_data(dask_client, node_data, history_dataframe)
        node_data = await historic_cluster_data.merge(node_data, historic_node_dataframe)
        node_data = await latest_cluster_data.check(node_data, all_supported_clusters_data)
        # JUST SEE IF ID IS IN THE RETURNED DATA, DO NOT CHECK FOR CLUSTER NAME
        # REQUEST FROM HISTORIC DATA
    except UnboundLocalError:
        pass
    return node_data


async def subscriber_node_data(dask_client, ip, subscriber_dataframe):
    name = await dask_client.compute(subscriber_dataframe.name[subscriber_dataframe.ip == ip])
    contact = await dask_client.compute(subscriber_dataframe.contact[subscriber_dataframe.ip == ip])
    public_l0 = tuple(await dask_client.compute(subscriber_dataframe.public_l0[subscriber_dataframe.ip == ip]))
    public_l1 = tuple(await dask_client.compute(subscriber_dataframe.public_l1[subscriber_dataframe.ip == ip]))
    subscriber = {"name": name.values[0], "contact": contact.values[0], "ip": ip, "public_l0": public_l0,
                  "public_l1": public_l1}
    logging.info(f'{datetime.utcnow().strftime("%H:%M:%S")} - CREATED SUBSCRIBER DICTIONARY FOR {name.values[0].upper()} {ip}, PORTS: L0{public_l0} L1{public_l1}')
    public_l0 = list(public_l0)
    public_l1 = list(public_l1)
    public_l0.clear()
    public_l1.clear()
    del ip, name, contact, public_l0, public_l1
    return subscriber


async def init(dask_client, latest_tessellation_version, all_supported_cluster_data, configuration):
    subscriber_futures = []
    request_futures = []
    history_dataframe = await read.history(configuration)
    subscriber_dataframe = await read.subscribers(configuration)
    ips = await dask_client.compute(subscriber_dataframe["ip"])
    # use set() to remove duplicates
    for i, ip in enumerate(list(set(ips.values))):
        subscriber_futures.append(asyncio.create_task(subscriber_node_data(dask_client, ip, subscriber_dataframe)))
    for _ in subscriber_futures:
        subscriber = await _
        for k, v in subscriber.items():
            if k == "public_l0":
                for port in v:
                    layer = 0
                    request_futures.append(asyncio.create_task(do_checks(dask_client, subscriber, layer, port, latest_tessellation_version, all_supported_cluster_data, history_dataframe, configuration)))
            elif k == "public_l1":
                for port in v:
                    layer = 1
                    request_futures.append(asyncio.create_task(do_checks(dask_client, subscriber, layer, port, latest_tessellation_version, all_supported_cluster_data, history_dataframe, configuration)))
        # return list of futures to main() and run there
    return request_futures
