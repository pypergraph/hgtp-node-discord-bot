import re
from typing import List, Optional
import datetime as dt

from pydantic import BaseModel
from pydantic.error_wrappers import ValidationError

from assets.src import api
from assets.src.encode_decode import id_to_dag_address

IP_REGEX = "^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$"


class NodeBase(BaseModel):
    """This class is the base from which any node related object inherits, it's also the base for user data"""
    name: str
    id: str = None
    ip: str
    public_port: int
    layer: int
    contact: str | int | None


class NodeMetrics(BaseModel):
    """These node metrics can be set by accessing the "from_text(text)" classmethod using main- or testnet text resp"""

    cluster_association_time: float = None
    cpu_count: int = None
    one_m_system_load_average: float = None
    disk_space_free: float = None
    disk_space_total: float = None

    @classmethod
    def from_txt(cls, text):
        """Only mainnet or testnet is currently supported"""

        lst = ['process_uptime_seconds{application=', 'system_cpu_count{application=',
               'system_load_average_1m{application=', 'disk_free_bytes{application=',
               'disk_total_bytes{application=']
        for line in text.split("\n"):
            for idx, item in enumerate(lst):
                if type(item) != str:
                    continue
                elif line.startswith(item):
                    lst[idx] = float(line.split(" ")[1])
        return cls(cluster_association_time=int(lst[0]), cpu_count=int(lst[1]),
                   one_m_system_load_average=lst[2], disk_space_free=int(lst[3]), disk_space_total=int(lst[4]))


class Node(NodeBase, NodeMetrics):
    """The base model for every user node check"""
    index: Optional[int]
    p2p_port: int = None
    wallet_address: str = None
    wallet_balance: float = None
    cluster_name: str = None
    former_cluster_name: str = None
    last_known_cluster_name: str = None
    state: str = None
    cluster_state: str = None
    former_cluster_state: str = None
    cluster_connectivity: str = None
    former_cluster_connectivity: str = None
    former_node_cluster_session: str = None
    reward_state: bool = None
    former_reward_state: bool = None
    reward_true_count: int = None
    reward_false_count: int = None
    former_cluster_association_time: float = None
    cluster_dissociation_time: float = None
    former_cluster_dissociation_time: float = None
    node_cluster_session: str = None
    latest_cluster_session: str = None
    node_peer_count: int = None
    cluster_peer_count: int = None
    former_cluster_peer_count: int = None
    version: str = None
    cluster_version: str = None
    latest_version: str = None
    notify: bool = None
    last_notified_timestamp: dt.datetime = None
    timestamp_index: dt.datetime = None
    former_timestamp_index: dt.datetime = None
    cluster_check_ordinal: str = None


class Cluster(BaseModel):
    """Will need to be tied to a wallet! The base model for every cluster data, this object is created pre-user node checks"""
    name: str
    id: str = None
    ip: str = None
    public_port: int = None
    layer: int
    contact: str | int | None
    wallet: str = None
    state: str = "offline"
    peer_count: int = 0
    session: str = None
    version: str = None
    latest_ordinal: int = 1
    latest_ordinal_timestamp: dt.datetime = None
    recently_rewarded: List = []
    peer_data: List = []


class User(NodeBase):
    """This class can create a user object which can be subscribed using different methods and transformations"""
    date: Optional[dt.datetime]
    # UserRead should be UserEnum
    index: Optional[int]
    type: str
    wallet: str

    # VALIDATE ID VALUE, CREATE CUSTOM EXCEPTION!

    @staticmethod
    async def get_id(ip: str, port: str, mode, configuration):
        """Will need refactoring before metagraph release. Some other way to validate node?"""
        if mode == "subscribe":
            node_data = await api.safe_request(f"http://{ip}:{port}/node/info", configuration)
            return str(node_data["id"]) if node_data is not None else None
        else:
            return None

    @classmethod
    async def discord(cls, configuration, process_msg, mode: str, name: str, contact: int, *args):
        """Treats a Discord message as a line of arguments and returns a list of subscribable user objects"""
        from assets.src.discord.discord import update_subscription_process_msg
        user_data = []
        invalid_user_data = []
        wallet = None
        process_msg = await update_subscription_process_msg(process_msg, 1, None)
        ips = {ip for ip in args if re.match(IP_REGEX, ip)}
        ip_idx = [args.index(ip) for ip in ips]
        for idx in range(0, len(ip_idx)):
            # Split arguments into lists before each IP
            arg = args[ip_idx[idx]:ip_idx[idx + 1]] if idx + 1 < len(ip_idx) else args[ip_idx[idx]:]
            for i, val in enumerate(arg):
                if val.lower() in ("z", "-z", "zero", "--zero", "l0", "-l0"):
                    for port in arg[i + 1:]:
                        if port.isdigit():
                            process_msg = await update_subscription_process_msg(process_msg, 2, f"{arg[0]}:{port}")
                            # Check if port is subscribed?
                            id_ = await User.get_id(arg[0], port, mode, configuration)
                            if id_ is not None:
                                wallet = id_to_dag_address(id_)
                                try:
                                    user_data.append(
                                        cls(name=name, contact=contact, id=id_, wallet=wallet,
                                            ip=arg[0], public_port=port, layer=0, type="discord"))
                                except ValidationError:
                                    pass
                            else:
                                invalid_user_data.append((arg[0], port, 0))
                        else:
                            break
                elif val.lower() in ("o", "-o", "one", "--one", "l1", "-l1"):
                    for port in arg[i + 1:]:
                        if port.isdigit():
                            process_msg = await update_subscription_process_msg(process_msg, 2, f"{arg[0]}:{port}")
                            id_ = await User.get_id(arg[0], port, mode, configuration)
                            if id_ is not None:
                                wallet = id_to_dag_address(id_)
                                try:
                                    user_data.append(
                                        cls(name=name, contact=contact, id=id_, wallet=wallet,
                                            ip=arg[0], public_port=port, layer=1, type="discord"))
                                except ValidationError:
                                    pass
                            else:
                                invalid_user_data.append((arg[0], port, 1))
                        else:
                            break
        return user_data, invalid_user_data
