#######################################################################################################################
#                       |    -**  MAINNET HGTP NODE SPIDER BOT MODULE, VERSION 1.0  **-    |
# --------------------------------------------------------------------------------------------------------------------
#  + DESCRIPTION
#   THIS MODULE CONTAINS PROJECT- OR BUSINESS-SPECIFIC CODE WHICH ENABLES SUPPORT FOR THIS PARTICULAR CLUSTER'S API.
# --------------------------------------------------------------------------------------------------------------------
#######################################################################################################################
# * IMPORTS: MODULES, CONSTANTS AND VARIABLES
# ---------------------------------------------------------------------------------------------------------------------

import asyncio
import logging
from datetime import datetime, timedelta

import nextcord.embeds
import nextcord
import pandas as pd

from assets.src import schemas, cluster, api

CONNECT_STATES = ("waitingfordownload", "downloadinprogress", "observing")

"""
    SECTION 1: PRELIMINARIES
"""


# ---------------------------------------------------------------------------------------------------------------------
# + CLUSTER SPECIFIC FUNCTIONS AND CLASSES GOES HERE
# ---------------------------------------------------------------------------------------------------------------------
#   THE FUNCTION BELOW IS ONE OF THE FIRST INITIATIONS. THIS FUNCTION REQUESTS DATA FROM THE MAINNET/TESTNET CLUSTER.
#   IN THIS MODULE WE REQUEST THINGS LIKE STATE, LOAD BALANCER ID, PEERS AND THE LATEST CLUSTER SESSION TOKEN.
#   WE THEN AGGREAGATE ALL THIS DATA IN A "CLUSTER DICTIONARY" AND ADDS IT TO A LIST OF ALL THE SUPPORTED CLUSTERS.
#   WE ALSO CHECK FOR REWARDS.
# ---------------------------------------------------------------------------------------------------------------------


async def request_cluster_data(
        session, url, layer, name, configuration
) -> schemas.Cluster:
    cluster_resp, status_code = await api.safe_request(
        session,
        f"{url}/{configuration['modules'][name][layer]['info']['cluster']}",
        configuration,
    )
    node_resp, status_code = await api.safe_request(
        session,
        f"{url}/{configuration['modules'][name][layer]['info']['node']}",
        configuration,
    )
    latest_ordinal, latest_timestamp, addresses = await locate_rewarded_addresses(
        session, layer, name, configuration
    )

    if node_resp is None:
        cluster_data = schemas.Cluster(
            layer=layer,
            name=name,
            id=await cluster.locate_id_offline(layer, name, configuration),
            peer_count=len(cluster_resp) if cluster_resp is not None else 0,
            latest_ordinal=latest_ordinal,
            latest_timestamp=latest_timestamp,
            recently_rewarded=addresses,
            peer_data=sorted(cluster_resp, key=lambda d: d["id"])
            if cluster_resp is not None
            else [],
        )
    else:
        cluster_data = schemas.Cluster(
            layer=layer,
            name=name,
            state=node_resp["state"].lower(),
            id=node_resp["id"],
            session=str(node_resp["clusterSession"]),
            version=node_resp["version"],
            ip=node_resp["host"],
            public_port=node_resp["publicPort"],
            peer_count=len(cluster_resp) if cluster_resp is not None else 0,
            latest_ordinal=latest_ordinal,
            latest_timestamp=latest_timestamp,
            recently_rewarded=addresses,
            peer_data=sorted(cluster_resp, key=lambda d: d["id"])
            if cluster_resp is not None
            else [],
        )
    # await config.update_config_with_latest_values(cluster_data, configuration)
    return cluster_data


# THE ABOVE FUNCTION ALSO REQUEST THE MOST RECENT REWARDED ADDRESSES. THIS FUNCTION LOCATES THESE ADDRESSES BY
# REQUESTING THE RELEVANT API'S.

# (!) YOU COULD MAKE 50 (MAGIC NUMBER) VARIABLE IN THE CONFIG YAML.
#     YOU MIGHT ALSO BE ABLE TO IMPROVE ON THE TRY/EXCEPT BLOCK LENGTH.


async def locate_rewarded_addresses(session, layer, name, configuration):
    """layer 1 doesn't have a block explorer: defaulting to 0"""
    # Can still not properly handle if latest_ordinal is None
    try:
        addresses = []
        latest_ordinal, latest_timestamp = await request_snapshot(
            session,
            f"{configuration['modules'][name][0]['be']['url'][0]}/"
            f"{configuration['modules'][name][0]['be']['info']['latest snapshot']}",
            configuration,
        )
        if latest_ordinal:
            tasks = []
            for ordinal in range(latest_ordinal - 50, latest_ordinal):
                tasks.append(
                    asyncio.create_task(
                        request_reward_addresses_per_snapshot(
                            session,
                            f"{configuration['modules'][name][0]['be']['url'][0]}/"
                            f"global-snapshots/{ordinal}/rewards",
                            configuration,
                        )
                    )
                )
            for task in tasks:
                addresses.extend(await task)
                addresses = list(set(addresses))
        return latest_ordinal, latest_timestamp, addresses
    except KeyError:
        return None, None, []
        # latest_ordinal = None; latest_timestamp = None; addresses = []
    # return latest_ordinal, latest_timestamp, addresses


# IN THE FUNCTIOM ABOVE WE NEED TO REQUEST SNAPSHOT DATA, BEFORE BEING ABLE TO KNOW WHICH REWARD SNAPSHOTS WE WANT TO
# CHECK AGAINST. THIS IS DONE IN THE FUNCTION BELOW.


async def request_snapshot(session, request_url, configuration):
    while True:
        data, status_code = await api.safe_request(session, request_url, configuration)
        if data:
            ordinal = data["data"]["ordinal"]
            try:
                timestamp = datetime.strptime(
                    data["data"]["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ"
                )
            except ValueError:
                timestamp = datetime.strptime(
                    data["data"]["timestamp"], "%Y-%m-%dT%H:%M:%SZ"
                )
            return ordinal, timestamp
        else:
            await asyncio.sleep(3)


async def request_reward_addresses_per_snapshot(session, request_url, configuration):
    while True:
        data, status_code = await api.safe_request(session, request_url, configuration)
        if data:
            lst = list(
                data_dictionary["destination"] for data_dictionary in data["data"]
            )
            return lst if lst else []
        else:
            logging.getLogger("app").warning(
                f"constellation.py - {request_url} returned {data} code={status_code}: forcing retry"
            )
            await asyncio.sleep(3)


"""
    SECTION 2: INDIVIDUAL NODE DATA PROCESSING
"""
# ---------------------------------------------------------------------------------------------------------------------
# + NODE SPECIFIC FUNCTIONS AND CLASSES GOES HERE
# ---------------------------------------------------------------------------------------------------------------------

yellow_color_trigger = False
red_color_trigger = False


async def node_cluster_data(
        session, node_data: schemas.Node, module_name, configuration: dict
) -> schemas.Node:
    """Get node data. IMPORTANT: Create Pydantic Schema for node data"""
    if node_data.public_port:
        node_info_data, status_code = await api.safe_request(
            session,
            f"http://{node_data.ip}:{node_data.public_port}/"
            f"{configuration['modules'][module_name][node_data.layer]['info']['node']}",
            configuration,
        )
        node_data.state = (
            "offline" if node_info_data is None else node_info_data["state"].lower()
        )
        if node_info_data:
            node_data.node_cluster_session = str(node_info_data["clusterSession"])
            node_data.version = node_info_data["version"]
            node_data.id = node_info_data["id"]
        if node_data.state != "offline":
            cluster_data, status_code = await api.safe_request(
                session,
                f"http://{node_data.ip}:{node_data.public_port}/"
                f"{configuration['modules'][module_name][node_data.layer]['info']['cluster']}",
                configuration,
            )
            metrics_data, status_code = await api.safe_request(
                session,
                f"http://{node_data.ip}:{node_data.public_port}/"
                f"{configuration['modules'][module_name][node_data.layer]['info']['metrics']}",
                configuration,
            )
            if cluster_data:
                node_data.node_peer_count = len(cluster_data)
            if metrics_data:
                node_data.cluster_association_time = (
                    metrics_data.cluster_association_time
                )
                node_data.cpu_count = metrics_data.cpu_count
                node_data.one_m_system_load_average = (
                    metrics_data.one_m_system_load_average
                )
                node_data.disk_space_free = metrics_data.disk_space_free
                node_data.disk_space_total = metrics_data.disk_space_total
        node_data = await request_wallet_data(
            session, node_data, module_name, configuration
        )
        node_data = set_connectivity_specific_node_data_values(node_data, module_name)
        node_data = set_association_time(node_data)

    return node_data


def check_rewards(node_data: schemas.Node, cluster_data: schemas.Cluster):
    if node_data.wallet_address in cluster_data.recently_rewarded:
        node_data.reward_state = True
        former_reward_count = (
            0 if node_data.reward_true_count is None else node_data.reward_true_count
        )
        node_data.reward_true_count = former_reward_count + 1
        if node_data.reward_false_count is None:
            node_data.reward_false_count = 0
    elif node_data.wallet_address not in cluster_data.recently_rewarded:
        node_data.reward_state = False
        former_reward_count = (
            0 if node_data.reward_false_count is None else node_data.reward_false_count
        )
        node_data.reward_false_count = former_reward_count + 1
        if node_data.reward_true_count is None:
            node_data.reward_true_count = 0

    return node_data


async def request_wallet_data(
        session, node_data: schemas.Node, module_name, configuration
) -> schemas.Node:
    wallet_data, status_code = await api.safe_request(
        session,
        f"{configuration['modules'][module_name.lower()][0]['be']['url'][0]}/addresses/{node_data.wallet_address}/balance",
        configuration,
    )
    if wallet_data is not None:
        node_data.wallet_balance = wallet_data["data"]["balance"]
    else:
        logging.getLogger("app").warning(
            f"constellation.py - {configuration['modules'][module_name.lower()][0]['be']['url'][0]}/addresses/{node_data.wallet_address}/balance returned code={status_code}"
        )

    return node_data


"""
    SECTION 3: PROCESS AND CALCULATE CLUSTER SPECIFIC NODE DATA.
"""


# ---------------------------------------------------------------------------------------------------------------------
# + LIKE ASSOCIATION AND DISSOCIATION... FUNCTIONS WHICH SHOULD ONLY RUN IF A CLUSTER/MODULE EXISTS.
# ---------------------------------------------------------------------------------------------------------------------


def set_connectivity_specific_node_data_values(node_data: schemas.Node, module_name):
    """Determine the connectivity of the node.
    We might need to add some more clarity to how the node has been connected. Like: former_name, latest_name, etc.
    """

    def set_association():
        if session != former_session:
            # If node just started connecting
            if node_data.state in CONNECT_STATES:
                logging.getLogger("app").debug(
                    f"constellation.py - Connect {module_name} by {node_data.name} ({node_data.ip}:"
                    f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
                )
                node_data.cluster_connectivity = "connecting"
            else:
                logging.getLogger("app").debug(
                    f"constellation.py - New association with {module_name} by {node_data.name} ({node_data.ip}:"
                    f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
                )
                node_data.cluster_connectivity = "new association"
                node_data.last_known_cluster_name = module_name

        else:
            # If node was connecting before and now has connection
            if node_data.state == "ready" and node_data.former_state in CONNECT_STATES:
                node_data.cluster_connectivity = "new association"
                node_data.last_known_cluster_name = module_name
            # If node is consecutively connecting
            elif node_data.state in CONNECT_STATES:
                logging.getLogger("app").debug(
                    f"constellation.py - Connect {module_name} by {node_data.name} ({node_data.ip}:"
                    f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
                )
                node_data.cluster_connectivity = "connecting"
            else:
                logging.getLogger("app").debug(
                    f"constellation.py - {module_name.title()} is associated with {node_data.name} ({node_data.ip}:"
                    f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
                )
                node_data.cluster_connectivity = "association"

    def set_dissociation():
        if session == former_session:
            # We know that the session isn't the latest session but the node could be consecutively
            # dissoc. with the former cluster and just be missing the current cluster name due to connection
            # error (hypothetically).
            logger.debug(
                f"constellation.py - {module_name.title()} is dissoc. with {node_data.name} ({node_data.ip}:"
                f"{node_data.public_port}, L{node_data.layer}): former session is the same as the current"
                f"{session, former_session, latest_session}"
            )
            node_data.cluster_connectivity = "dissociation"
        else:
            logger.debug(
                f"constellation.py - New dissociation with {module_name} by {node_data.name} ({node_data.ip}:"
                f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
            )
            node_data.cluster_connectivity = "new dissociation"
            node_data.last_known_cluster_name = former_name

    def set_uncertain():
        logger.debug(
            f"constellation.py - {node_data.name.title()} ({node_data.ip}:{node_data.public_port}, L{node_data.layer}) could not establish connection to {module_name.title()}"
        )
        node_data.cluster_connectivity = "uncertain"

    logger = logging.getLogger("app")

    former_name = node_data.former_cluster_name
    curr_name = node_data.cluster_name
    session = node_data.node_cluster_session
    latest_session = node_data.latest_cluster_session
    former_session = node_data.former_node_cluster_session
    # latest_session is only registered if something crucial... But what? If cluster_data is found, right?
    # And I only need to register when cluster_data is found, right? How about when report is requested?
    if session and latest_session:
        # "latest_session" is None due to connection error or dissoc.
        if session < latest_session:
            # In case the node is dissociated from a known cluster.
            # Could be dissoc. in the following ways:
            # "session" is None due to connection error or dissoc.
            if not curr_name:
                # In cas of a dissoc. the current cluster name will be None.
                # The current cluster name can be missing due to connection error (false negative)
                if former_name:
                    # If the current cluster name is None and there's a former cluster name found, the
                    # dissoc. must be recent. However, the current cluster name could be missing due to a false negative.
                    # Therefore, we check to see if session is the same as former session (might not make difference now
                    # but could come in handy).
                    set_dissociation()
                else:
                    # We know the latest session is found and the node is not part of this cluster.
                    # If cluster name is None and former cluster name is also None.
                    # Then we have the possibility of a consecutive dissoc., if session and former session match (since
                    # both will be None). If session and former session doesn't match, then we have a new dissoc.
                    # (because this can't be the latest session).
                    set_dissociation()

            else:
                logger.debug(
                    f"constellation.py -  {node_data.name} ({node_data.ip}) forked {module_name.title()}:"
                    f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
                )
                node_data.cluster_connectivity = "forked"

        elif session == latest_session:
            # If new connection is made with this node then alert
            if curr_name == module_name:
                # If former name is None: could be due to uncertain connection
                if not former_name:
                    set_association()
                else:
                    set_association()
            else:
                logger.debug(
                    f"constellation.py - {module_name.title()} is associated with {node_data.name} ({node_data.ip}:{node_data.public_port}, L{node_data.layer}): Due to session being the latest ({session, latest_session})"
                )
                node_data.cluster_connectivity = "association"
        else:
            logger.debug(
                f"constellation.py -  {node_data.name} ({node_data.ip}) forked {module_name.title()}:"
                f"{node_data.public_port}, L{node_data.layer}): Sessions {session, latest_session}"
            )
            node_data.cluster_connectivity = "forked"

    else:
        # If edge node is under maintenance or connection error
        if session and former_session:
            # If neither session nor the former session is None
            # we have the possibility of node association but connection error with the edge node
            if session == former_session and node_data.state == "ready":
                # If the session didn't change we don't need to alert anyone just yet.
                logger.debug(
                    f"constellation.py - {module_name.title()} is associated with {node_data.name} ({node_data.ip}):"
                    f"{node_data.public_port}, L{node_data.layer}): due to session being the latest "
                    f"({session, latest_session}) [Edge node is down]"
                )
                node_data.cluster_connectivity = "association"
            else:
                set_uncertain()
        else:
            # If either session or the former session is None
            set_uncertain()

    return node_data


def set_association_time(node_data: schemas.Node):
    if node_data.former_timestamp_index is not None:
        # LINE BELOW IS TEMPORARY
        time_difference = (
                pd.Timestamp(node_data.timestamp_index)
                - pd.Timestamp(node_data.former_timestamp_index)
        ).seconds
    else:
        time_difference = node_data.timestamp_index.second

    if node_data.cluster_association_time is None:
        node_data.cluster_association_time = 0
    if node_data.former_cluster_association_time is None:
        node_data.former_cluster_association_time = 0
    if node_data.cluster_dissociation_time is None:
        node_data.cluster_dissociation_time = 0
    if node_data.former_cluster_dissociation_time is None:
        node_data.former_cluster_dissociation_time = 0

    if node_data.cluster_connectivity == "association":
        node_data.cluster_association_time = (
                time_difference + node_data.former_cluster_association_time
        )
        node_data.cluster_dissociation_time = node_data.former_cluster_dissociation_time
    elif node_data.cluster_connectivity in ("dissociation", "forked"):
        node_data.cluster_dissociation_time = (
                time_difference + node_data.former_cluster_dissociation_time
        )
        node_data.cluster_association_time = node_data.former_cluster_association_time
    elif node_data.cluster_connectivity in ("new association", "new dissociation"):
        node_data.cluster_association_time = node_data.former_cluster_association_time
        node_data.cluster_dissociation_time = node_data.former_cluster_dissociation_time
    elif node_data.cluster_connectivity == ("uncertain", "connecting"):
        node_data.cluster_association_time = node_data.former_cluster_association_time
        node_data.cluster_dissociation_time = node_data.former_cluster_dissociation_time

    return node_data


"""
    SECTION 4: CREATE REPORT
"""


def build_title(node_data: schemas.Node) -> str:
    cluster_name = None
    names = [cluster for cluster in (
        node_data.cluster_name,
        node_data.former_cluster_name,
        node_data.last_known_cluster_name,
    ) if cluster]
    if names:
        cluster_name = names[0]
    if node_data.cluster_connectivity == "connecting":
        title_ending = f"CONNECTING"
    elif node_data.cluster_connectivity in ("new association", "association"):
        title_ending = f"UP"
    elif node_data.cluster_connectivity in ("new dissociation", "dissociation"):
        title_ending = f"DOWN"
    elif node_data.cluster_connectivity == "forked":
        title_ending = f"FORKED"
    elif node_data.reward_state is False:
        title_ending = f"MISSING REWARDS"
    elif node_data.cluster_connectivity == "uncertain":
        title_ending = f"UNSTABLE CONNECTION"
    else:
        title_ending = f"REPORT"
    if cluster_name is not None:
        return f"{cluster_name.title()} L{node_data.layer} ({node_data.ip}): {title_ending}"
    else:
        return f"L{node_data.layer} ({node_data.ip}): {title_ending}"


def build_general_node_state(node_data: schemas.Node) -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def node_state_field() -> str:
        if node_data.id is not None:
            return (
                f"{field_symbol} **NODE**\n"
                f"```\n"
                f"Peers: {node_data.node_peer_count}\n"
                f"ID: {node_data.id[:6]}...{node_data.id[-6:]}\n"
                f"IP: {node_data.ip}\n"
                f"Subscribed Port: {node_data.public_port}\n"
                f"State: {node_state}```"
                f"{field_info}"
            )
        elif node_data.id is None:
            return (
                f"{field_symbol} **NODE**\n"
                f"```\n"
                f"Peers: {node_data.node_peer_count}\n"
                f"IP: {node_data.ip}\n"
                f"Subscribed Port: {node_data.public_port}\n"
                f"State: {node_state}```"
                f"{field_info}"
            )

    if node_data.state not in ("offline", "waitingfordownload", "downloadinprogress", "readytojoin", None):
        if node_data.cluster_peer_count in (None, 0):
            if node_data.cluster_connectivity in ("new association", "association"):
                field_symbol = ":green_square:"
                field_info = f"`ⓘ  Node is connected but the load balancer is unstable or the network is undergoing maintenance`"
                node_state = node_data.state.title()
                return node_state_field(), False, False
            elif node_data.cluster_connectivity == "forked":
                field_symbol = ":red_square:"
                field_info = f"`⚠  Node has forked and the load balancer is unstable or the network is undergoing maintenance`"
                node_state = node_data.state.title()
                red_color_trigger = True
                return node_state_field(), red_color_trigger, False
            elif node_data.cluster_connectivity in ("new dissociation", "dissociation"):
                field_symbol = ":red_square:"
                field_info = f"`⚠  Node is disconnected and the load balancer is unstable or the network is undergoing maintenance`"
                node_state = node_data.state.title()
                red_color_trigger = True
                return node_state_field(), red_color_trigger, False
            else:
                field_symbol = ":yellow_square:"
                field_info = f'⚠  Node connection is uncertain and the load balancer is unstable or the network is undergoing maintenance'
                node_state = node_data.state.title()
                yellow_color_trigger = True
                return node_state_field(), False, yellow_color_trigger
        elif node_data.node_peer_count in (None, 0):
            field_info = f"`⚠  The node is not connected to any cluster peers`"
            field_symbol = ":red_square:"
            node_state = node_data.state.title()
            red_color_trigger = True
            return node_state_field(), red_color_trigger, False
        else:
            field_info = f"`ⓘ  Connected to {round(float(node_data.node_peer_count * 100 / node_data.cluster_peer_count), 2)}% of the cluster peers`"
            field_symbol = ":green_square:"
            node_state = node_data.state.title()
            return node_state_field(), False, False
    elif node_data.state in ("waitingfordownload", "downloadinprogress", "readytojoin"):
        field_symbol = ":yellow_square:"
        if node_data.state == "readytojoin":
            field_info = f"`ⓘ  The node is ready to join a cluster`"
        else:
            field_info = f"`ⓘ  The node is attempting to establish connection to the cluster`"
        node_state = node_data.state.title()
        yellow_color_trigger = True
        return node_state_field(), False, yellow_color_trigger
    else:
        field_symbol = f":red_square:"
        field_info = f"`⚠  The node is not associated with the previously associated cluster`"
        node_state = "Offline"
        red_color_trigger = True
        return node_state_field(), red_color_trigger, False


def build_general_cluster_state(node_data: schemas.Node, module_name) -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def general_cluster_state_field() -> str:
        if node_data.cluster_peer_count > 0:
            return (
                f"{field_symbol} **{module_name.upper()} CLUSTER**\n"
                f"```\n"
                f"Peers:   {node_data.cluster_peer_count}\n"
                f"Assoc.:  {timedelta(seconds=float(node_data.cluster_association_time)).days} days {round(association_percent(), 2)}%\n"
                f"Dissoc.: {timedelta(seconds=float(node_data.cluster_dissociation_time)).days} days {round(100.00 - association_percent(), 2)}%```"
                f"{field_info}"
            )
        else:
            return (
                f"{field_symbol} **{module_name.upper()} CLUSTER**\n"
                f"```\n"
                f"Peers:   {node_data.node_peer_count}\n"
                f"Assoc.:  {timedelta(seconds=float(node_data.cluster_association_time)).days} days {round(association_percent(), 2)}%\n"
                f"Dissoc.: {timedelta(seconds=float(node_data.cluster_dissociation_time)).days} days {round(100.00 - association_percent(), 2)}%```"
                f"{field_info}"
            )

    def association_percent() -> float:
        if node_data.cluster_association_time not in (
                0,
                None,
        ) and node_data.cluster_dissociation_time not in (0, None):
            down_percent = float(node_data.cluster_dissociation_time) / (
                    float(node_data.cluster_association_time)
                    + float(node_data.cluster_dissociation_time)
            )
            up_percent = float(1 - down_percent) * 100
            return float(up_percent)
        elif node_data.cluster_association_time not in (
                0,
                None,
        ) and node_data.cluster_dissociation_time in (0, None):
            return round(float(100.0), 2)
        elif node_data.cluster_association_time in (
                0,
                None,
        ) and node_data.cluster_dissociation_time not in (0, None):
            return round(float(0.0), 2)
        else:
            return round(float(0.0), 2)

    if node_data.cluster_connectivity == "new association":
        field_symbol = ":green_square:"
        field_info = f"`ⓘ  Association with the cluster was recently established`"
        return general_cluster_state_field(), False, False
    elif node_data.cluster_connectivity == "association":
        field_symbol = ":green_square:"
        field_info = f"`ⓘ  The node is consecutively associated with the cluster`"
        return general_cluster_state_field(), False, False
    elif node_data.cluster_connectivity == "new dissociation":
        field_symbol = ":red_square:"
        field_info = f"`⚠  The node was recently dissociated from the cluster`"
        red_color_trigger = True
        return general_cluster_state_field(), red_color_trigger, False
    elif node_data.cluster_connectivity == "dissociation":
        field_symbol = ":red_square:"
        field_info = f"`⚠  The node is consecutively dissociated from the cluster`"
        red_color_trigger = True
        return general_cluster_state_field(), red_color_trigger, False
    elif node_data.cluster_connectivity == "connecting":
        field_symbol = ":green_square:"
        field_info = f"`ⓘ  The node is connecting to a cluster`"
        return general_cluster_state_field(),False, False
    elif node_data.cluster_connectivity == "forked":
        field_symbol = ":red_square:"
        field_info = f"`⚠  The node has forked`"
        red_color_trigger = True
        return general_cluster_state_field(), red_color_trigger, False
    elif node_data.cluster_connectivity == "uncertain":
        field_symbol = ":yellow_square:"
        field_info = f"`⚠  Could not establish connection to the edge node`"
        yellow_color_trigger = True
        return general_cluster_state_field(), False, yellow_color_trigger
    elif node_data.cluster_connectivity is None:
        field_symbol = ":yellow_square:"
        field_info = f"`⚠  Please report to hgtp_michael: connectivity state is None`"
        yellow_color_trigger = True
        return general_cluster_state_field(), False, yellow_color_trigger
    else:
        logging.getLogger("app").warning(
            f"constellation.py - {node_data.cluster_connectivity.title()} is not a supported node state ({node_data.name}, {node_data.ip}:{node_data.public_port}, L{node_data.layer})"
        )
        field_symbol = ":yellow_square:"
        field_info = f"`⚠  Please contact hgtp_michael: cluster connectivity is {node_data.cluster_connectivity}`"
        yellow_color_trigger = True
        return general_cluster_state_field(), False, yellow_color_trigger


def build_general_node_wallet(node_data: schemas.Node, module_name) -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def generate_field_from_reward_states() -> tuple[str, bool, bool]:
        def wallet_field() -> str:
            if node_data.layer == 1:
                return (
                    f"{field_symbol} **WALLET**\n"
                    f"```\n"
                    f"Address: {node_data.wallet_address}\n"
                    f"Balance: {node_data.wallet_balance / 100000000} ＄DAG```"
                    f"{field_info}"
                )
            else:
                return (
                    f"{field_symbol} **WALLET**\n"
                    f"```\n"
                    f"Address: {node_data.wallet_address}\n"
                    f"Balance: {node_data.wallet_balance / 100000000} ＄DAG```"
                    f"{field_info}"
                )

        if module_name == "mainnet" and node_data.wallet_balance <= 250000 * 100000000:
            field_symbol = ":red_square:"
            field_info = f"`⚠  The wallet doesn't hold sufficient collateral`"
            red_color_trigger = True
            yellow_color_trigger = False
            return wallet_field(), red_color_trigger, yellow_color_trigger
        elif (
                node_data.reward_state in (False, None)
                and node_data.former_reward_state is True
        ):
            if module_name == "mainnet":
                field_symbol = ":red_square:"
                field_info = (
                    f":red_circle:` The wallet recently stopped receiving rewards`"
                )
                red_color_trigger = True
                yellow_color_trigger = False
                return wallet_field(), red_color_trigger, yellow_color_trigger
            elif module_name in ("integrationnet", "testnet"):
                field_symbol = ":green_square:"
                field_info = (
                    f":red_circle:` The {module_name.title()}-wallet recently stopped receiving ({module_name.title()}) $DAG rewards. "
                    f"However, this might not affect the rewards transferred to your registered mainnet wallet`"
                )
                red_color_trigger = False
                yellow_color_trigger = False
                return wallet_field(), red_color_trigger, yellow_color_trigger
        elif node_data.reward_state in (
                False,
                None,
        ) and node_data.former_reward_state in (False, None):
            if node_data.layer == 1:
                field_symbol = ":green_square:"
                field_info = (
                    f"`ⓘ  {module_name.title()} layer one does not currently distribute rewards. "
                    f"Please refer to the layer 0 report`"
                )
                red_color_trigger = False
                yellow_color_trigger = False
                return wallet_field(), red_color_trigger, yellow_color_trigger
            else:
                if module_name == "mainnet":
                    field_symbol = ":red_square:"
                    field_info = f":red_circle:` The wallet doesn't receive rewards`"
                    red_color_trigger = True
                    yellow_color_trigger = False
                    return wallet_field(), red_color_trigger, yellow_color_trigger
                elif module_name in ("integrationnet", "testnet"):
                    field_symbol = ":green_square:"
                    field_info = (
                        f":red_circle:` The {module_name.title()}-wallet doesn't receive ({module_name.title()}) $DAG rewards. "
                        f"However, this might not affect the rewards transferred to your registered mainnet wallet`"
                    )
                    red_color_trigger = False
                    yellow_color_trigger = False
                    return wallet_field(), red_color_trigger, yellow_color_trigger
        elif node_data.reward_state is True and node_data.former_reward_state in (
                False,
                None,
        ):
            field_symbol = ":green_square:"
            field_info = f":coin:` The wallet recently started receiving rewards`"
            red_color_trigger = False
            yellow_color_trigger = False
            return wallet_field(), red_color_trigger, yellow_color_trigger
        elif node_data.reward_state is True and node_data.former_reward_state is True:
            field_symbol = ":green_square:"
            field_info = f":coin:` The wallet receives rewards`"
            red_color_trigger = False
            yellow_color_trigger = False
            return wallet_field(), red_color_trigger, yellow_color_trigger
        else:
            field_symbol = ":yellow_square:"
            field_info = (
                f"`ⓘ  Please report to hgtp_michael: the wallet reward state is unknown.`\n"
                f"`ⓘ  No minimum collateral required`"
            )
            red_color_trigger = False
            yellow_color_trigger = True
            return wallet_field(), red_color_trigger, yellow_color_trigger

    if node_data.wallet_address is not None:
        field_content, red_color_trigger, yellow_color_trigger = generate_field_from_reward_states()
        return field_content, red_color_trigger, yellow_color_trigger
    else:
        return (f":yellow_square: **WALLET**\n"
                f"" f"`ⓘ  No data available`"), False, False


def build_system_node_version(node_data: schemas.Node) -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def version_field() -> str:
        return (
            f"{field_symbol} **TESSELLATION**\n"
            f"```\n"
            f"Version {node_data.version} installed```"
            f"{field_info}"
        )

    if node_data.version is not None and node_data.cluster_version is not None:
        if node_data.version == node_data.cluster_version:
            field_symbol = ":green_square:"
            if node_data.cluster_version == node_data.latest_version:
                field_info = "`ⓘ  You are running the latest version of Tessellation`"
            elif node_data.cluster_version < node_data.latest_version:
                field_info = f"`ⓘ  You are running the latest version but a new Tessellation release ({node_data.latest_version}) should soon be available`"
            elif node_data.cluster_version > node_data.latest_version:
                field_info = f"`ⓘ  You seem to be associated with a cluster running a test-release. Latest stable version is {node_data.latest_version}`"
            else:
                field_info = "`⚠  Please report this issue to hgtp_michael: version clutter`"
            return version_field(), False, False

        elif node_data.version < node_data.cluster_version:
            field_symbol = ":red_square:"
            field_info = f"`⚠  New Tessellation upgrade available (v{node_data.latest_version})`"
            red_color_trigger = True
            return version_field(), red_color_trigger, False
        elif node_data.version > node_data.cluster_version:
            field_symbol = ":red_square:"
            field_info = f"`⚠  Your Tessellation version is higher than the cluster version (v{node_data.cluster_version})`"
            red_color_trigger = True
            return version_field(), red_color_trigger, False
        else:
            field_symbol = ":red_square:"
            field_info = f"`⚠  Please report to hgtp_michael: latest version {node_data.latest_version}, cluster version {node_data.cluster_version}, node version {node_data.version}`"
            red_color_trigger = True
            return version_field(), red_color_trigger, False
    elif node_data.version is not None and node_data.latest_version is not None:
        if node_data.version > node_data.latest_version:
            field_symbol = ":green_square:"
            if node_data.version == node_data.cluster_version:
                field_info = f"`ⓘ  You seem to be associated with a cluster running a test-release. Latest stable version is {node_data.latest_version}`"
            else:
                field_info = f"`ⓘ  You seem to be running a test-release. Latest stable version is {node_data.latest_version}`"
            return version_field(), False, False
        else:
            field_symbol = ":yellow_square:"
            if node_data.cluster_peer_count in (0, None):
                field_info = f"`ⓘ  Could not determine the current cluster version due to unstable connection or maintenance but latest Github version is {node_data.latest_version}`"
            else:
                field_info = f"`ⓘ  Latest version is {node_data.latest_version}`"
            return version_field(), False, False

    else:
        return (f":yellow_square: **TESSELLATION**\n"
                f"" f"`ⓘ  No data available`"), False, True


def build_system_node_load_average(node_data: schemas.Node)  -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def load_average_field() -> str:
        return (
            f"{field_symbol} **CPU**\n"
            f"```\n"
            f"Count: {round(float(node_data.cpu_count))}\n"
            f"Load:  {round(float(node_data.one_m_system_load_average), 2)}```"
            f"{field_info}"
        )

    if (node_data.one_m_system_load_average or node_data.cpu_count) is not None:
        if float(node_data.one_m_system_load_average) / float(node_data.cpu_count) >= 1:
            field_symbol = ":red_square:"
            field_info = f'`⚠  "CPU load" is high (should be below "CPU count"). You might want to monitor CPU usage`'
            yellow_color_trigger = True
            return load_average_field(), red_color_trigger, yellow_color_trigger
        elif (
                float(node_data.one_m_system_load_average) / float(node_data.cpu_count) < 1
        ):
            field_symbol = ":green_square:"
            field_info = f'`ⓘ  "CPU load" is ok (should be below "CPU count")`'
            return load_average_field(), red_color_trigger, False
    else:
        field_symbol = ":yellow_square:"
        field_info = f"`⚠  Please report to hgtp_michael: None-type is present`"
        return load_average_field(), red_color_trigger, False


def build_system_node_disk_space(node_data: schemas.Node) -> tuple[str, bool: red_color_trigger, bool: yellow_color_trigger]:
    def disk_space_field() -> str:
        return (
            f"{field_symbol} **DISK**\n"
            f"```\n"
            f"Free:  {round(float(node_data.disk_space_free) / 1073741824, 2)} GB {round(float(node_data.disk_space_free) * 100 / float(node_data.disk_space_total), 2)}%\n"
            f"Total: {round(float(node_data.disk_space_total) / 1073741824, 2)} GB```"
            f"{field_info}"
        )

    if node_data.disk_space_free is not None:
        if (
                0
                <= float(node_data.disk_space_free)
                * 100
                / float(node_data.disk_space_total)
                <= 10
        ):
            field_symbol = ":red_square:"
            field_info = f"`⚠  Free disk space is low`"
            yellow_color_trigger = True
            return disk_space_field(), red_color_trigger, yellow_color_trigger
        else:
            field_symbol = ":green_square:"
            field_info = f"`ⓘ  Free disk space is ok`"
            return disk_space_field(), red_color_trigger, False


def build_embed(node_data: schemas.Node, module_name) -> nextcord.Embed:
    embed_created = False

    def determine_color_and_create_embed(yellow_color_trigger, red_color_trigger) -> nextcord.Embed:
        title = build_title(node_data).upper()
        if yellow_color_trigger and red_color_trigger is False:
            embed = nextcord.Embed(title=title, colour=nextcord.Color.orange())
            embed.set_thumbnail(
                url="https://raw.githubusercontent.com/pypergraph/hgtp-node-discord-bot/master/assets/src/images/logo-encased-teal.png"
            )
        elif red_color_trigger:
            embed = nextcord.Embed(title=title, colour=nextcord.Color.brand_red())
            embed.set_thumbnail(
                url="https://raw.githubusercontent.com/pypergraph/hgtp-node-discord-bot/master/assets/src/images/logo-encased-red.png"
            )

        else:
            embed = nextcord.Embed(title=title, colour=nextcord.Color.dark_teal())
            embed.set_thumbnail(
                url="https://raw.githubusercontent.com/pypergraph/hgtp-node-discord-bot/master/assets/src/images/logo-encased-teal.png"
            )

        return embed

    node_state, red_color_trigger, yellow_color_trigger = build_general_node_state(
        node_data
    )
    cluster_state, red_color_trigger, yellow_color_trigger = build_general_cluster_state(node_data, module_name)
    if (
            red_color_trigger is True or yellow_color_trigger is True
    ) and not embed_created:
        embed = determine_color_and_create_embed(
            yellow_color_trigger, red_color_trigger
        )
        embed_created = True
    if node_data.wallet_address is not None:
        node_wallet, red_color_trigger, yellow_color_trigger = build_general_node_wallet(node_data, module_name)
        if (
                red_color_trigger is True or yellow_color_trigger is True
        ) and not embed_created:
            embed = determine_color_and_create_embed(
                yellow_color_trigger, red_color_trigger
            )
            embed_created = True
    if node_data.version is not None:
        node_version, red_color_trigger, yellow_color_trigger = build_system_node_version(node_data)
        if (
                red_color_trigger is True or yellow_color_trigger is True
        ) and not embed_created:
            embed = determine_color_and_create_embed(
                yellow_color_trigger, red_color_trigger
            )
            embed_created = True
    if node_data.one_m_system_load_average is not None:
        node_load, red_color_trigger, yellow_color_trigger = build_system_node_load_average(node_data)
        if (
                red_color_trigger is True or yellow_color_trigger is True
        ) and not embed_created:
            embed = determine_color_and_create_embed(
                yellow_color_trigger, red_color_trigger
            )
            embed_created = True
    if node_data.disk_space_total is not None:
        node_disk, red_color_trigger, yellow_color_trigger = build_system_node_disk_space(node_data)
        if (
                red_color_trigger is True or yellow_color_trigger is True
        ) and not embed_created:
            embed = determine_color_and_create_embed(
                yellow_color_trigger, red_color_trigger
            )
    if not embed_created:
        embed = determine_color_and_create_embed(
            yellow_color_trigger, red_color_trigger
        )
    embed.set_author(name=node_data.name)
    embed.add_field(name="\u200B", value=node_state)
    embed.add_field(name=f"\u200B", value=cluster_state)
    if node_data.wallet_address is not None:
        embed.add_field(name=f"\u200B", value=node_wallet, inline=False)
    if node_data.version is not None:
        embed.add_field(name="\u200B", value=node_version, inline=False)
    if node_data.one_m_system_load_average is not None:
        embed.add_field(name="\u200B", value=node_load, inline=True)
    if node_data.disk_space_total is not None:
        embed.add_field(name="\u200B", value=node_disk, inline=True)

    return embed


"""
    SECTION 5: NOTIFICATION CONDITIONS
"""


def mark_notify(d: schemas.Node, configuration):
    # The hardcoded values should be adjustable in config_new.yml
    if d.cluster_connectivity in ("new association", "new dissociation"):
        d.notify = True
    elif d.former_cluster_connectivity != "connecting" and d.cluster_connectivity == "connecting":
        d.notify = True
        d.last_notified_reason = "connecting"
    elif d.last_notified_timestamp:
        if d.cluster_connectivity in ("forked", "uncertain", "connecting"):
            if (
                    d.timestamp_index - d.last_notified_timestamp
            ).total_seconds() >= timedelta(
                hours=configuration["general"]["notifications"][
                    "free disk space sleep (hours)"
                ]
            ).seconds or d.last_notified_reason in ("disk", "version", "rewards"):
                d.last_notified_timestamp = d.timestamp_index
                d.notify = True
                if d.cluster_connectivity == "forked":
                    d.last_notified_reason = "forked"
                elif d.cluster_connectivity == "connecting":
                    d.last_notified_reason = "connecting"
                else:
                    d.last_notified_reason = "uncertain"
        elif d.reward_state is False:
            if (
                    d.timestamp_index - d.last_notified_timestamp
            ).total_seconds() >= timedelta(
                hours=configuration["general"]["notifications"][
                    "free disk space sleep (hours)"
                ]
            ).seconds or d.last_notified_reason in ("disk", "version", "forked", "uncertain", "connecting"):
                # THIS IS A TEMPORARY FIX SINCE MAINNET LAYER 1 DOESN'T SUPPORT REWARDS
                d.notify = True
                d.last_notified_timestamp = d.timestamp_index
                d.last_notified_reason = "rewards"
        elif d.version and d.cluster_version:
            if d.version < d.cluster_version:
                if (
                    (d.timestamp_index.second - d.last_notified_timestamp.second)
                    >= timedelta(hours=6).seconds
                ) or d.last_notified_reason in ("rewards", "disk", "forked", "uncertain", "connecting"):
                    d.notify = True
                    d.last_notified_timestamp = d.timestamp_index
                    d.last_notified_reason = "version"
        elif d.disk_space_free and d.disk_space_total:
            if (
                    0
                    <= float((d.disk_space_free) * 100 / float(d.disk_space_total))
                    <= configuration["general"]["notifications"][
                "free disk space threshold (percentage)"
            ]
            ) or d.last_notified_reason in ("rewards", "version", "forked", "uncertain", "connecting"):
                if (
                        d.timestamp_index - d.last_notified_timestamp
                ).total_seconds() >= timedelta(
                    hours=configuration["general"]["notifications"][
                        "free disk space sleep (hours)"
                    ]
                ).seconds:
                    d.notify = True
                    d.last_notified_timestamp = d.timestamp_index
                    d.last_notified_reason = "disk"
    # IF NO FORMER DATA
    else:
        if d.cluster_connectivity == "connecting":
            d.notify = True
            d.last_notified_timestamp = d.timestamp_index
            d.last_notified_reason = "connecting"
        if d.reward_state is False:
            d.notify = True
            d.last_notified_timestamp = d.timestamp_index
            d.last_notified_reason = "rewards"
        elif d.version and d.cluster_version:
            if d.version < d.cluster_version:
                d.notify = True
                d.last_notified_timestamp = d.timestamp_index
                d.last_notified_reason = "version"
        elif (
                0
                <= float(d.disk_space_free) * 100 / float(d.disk_space_total)
                <= configuration["general"]["notifications"][
                    "free disk space threshold (percentage)"
                ]
        ):
            d.notify = True
            d.last_notified_timestamp = d.timestamp_index
            d.last_notified_reason = "disk"
    return d
