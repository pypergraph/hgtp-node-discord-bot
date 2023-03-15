async def node_data(dask_client, node_data, history_dataframe):

    # ISOLATE LAYER AND NODE IN HISTORIC DATA
    ip = None
    port = None
    for k, v in node_data.items():
        if k == "host":
            ip = v
        if k == "publicPort":
            port = v
    historic_node_dataframe = await dask_client.compute(history_dataframe[(history_dataframe["node ip"] == ip) & (history_dataframe["node port"] == port)])
    del ip, port, k, v
    print(historic_node_dataframe)
    return historic_node_dataframe


async def former_data(node_data, historic_node_data):
    former_node_data = historic_node_data[historic_node_data["index timestamp"] == historic_node_data["index timestamp"].max()]
    if not former_node_data.empty:
        former_cluster_names = list(set(former_node_data["cluster name"]))
        for cluster_name in former_cluster_names:
            former_tessellation_version = former_node_data["node version"][former_node_data["cluster name"] == cluster_name].values[0]
            former_connectivity = former_node_data["connectivity"][former_node_data["cluster name"] == cluster_name].values[0]
